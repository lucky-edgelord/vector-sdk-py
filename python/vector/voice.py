"""Voice: ``VoiceClient`` (discord.py's shape), audio sources, utterances and transcription.

Audio is 48 kHz mono signed 16-bit PCM, passed as little-endian ``bytes`` (one 20 ms frame is
960 samples = 1920 bytes). Compared with discord.py:

* ``vc.play(vector.FFmpegPCMAudio("song.mp3"), after=…)`` works the same way.
* Bots can *hear* too: ``async for speech in vc.listen(): …`` gives per-speaker frames, and
  :class:`Utterances` groups them into sentences for speech-to-text.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from .channel import VoiceChannel
    from .client import Client

_log = logging.getLogger("vector.voice")

__all__ = ("VoiceClient", "VoiceProtocol", "VoiceState", "AudioSource", "PCMAudio", "FFmpegPCMAudio",
           "PCMVolumeTransformer", "Speech", "Utterances", "Transcriber", "tone", "level", "SAMPLE_RATE",
           "FRAME_SAMPLES", "FRAME_BYTES")

SAMPLE_RATE = 48_000
FRAME_SAMPLES = 960
FRAME_BYTES = FRAME_SAMPLES * 2


def _native():
    from . import _native as n

    if not hasattr(n, "tone"):
        raise RuntimeError("this build of vector has no voice support (rebuild with the `voice` feature)")
    return n


def tone(hz: float, ms: int) -> bytes:
    """A sine tone as PCM bytes."""
    return _native().tone(hz, ms)


def level(pcm: bytes) -> float:
    """Loudness of a PCM buffer, 0.0–1.0."""
    return _native().level(pcm)


class VoiceState:
    """Someone's state in a voice Channel (``on_voice_state_update(member, before, after)``)."""

    def __init__(self, channel: Optional["VoiceChannel"], data: Dict[str, Any]):
        self.channel = channel
        self.self_mute: bool = bool(data.get("muted"))
        self.self_deaf: bool = bool(data.get("deafened"))
        self.mute: bool = bool(data.get("server_muted"))
        self.deaf: bool = bool(data.get("server_deafened"))
        self.self_video: bool = bool(data.get("camera"))
        self.self_stream: bool = bool(data.get("screen"))
        self.elsewhere: bool = bool(data.get("elsewhere"))
        self.suppress = False
        self.requested_to_speak_at = None
        self.afk = False
        self.raw = data

    camera = property(lambda self: self.self_video)
    screen = property(lambda self: self.self_stream)

    def __repr__(self) -> str:
        return f"<VoiceState channel={getattr(self.channel, 'name', None)!r} self_mute={self.self_mute} self_video={self.self_video}>"


class AudioSource:
    """Yields 20 ms PCM frames (``FRAME_BYTES`` each). Return ``b""`` when finished."""

    def read(self) -> bytes:
        raise NotImplementedError

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        pass

    async def load(self) -> None:
        """Optional async preparation before playback."""

    def __del__(self) -> None:
        self.cleanup()


class PCMAudio(AudioSource):
    """Raw PCM from bytes or a binary stream."""

    def __init__(self, stream: Any):
        self._buf = stream if isinstance(stream, (bytes, bytearray)) else None
        self._stream = None if self._buf is not None else stream
        self._pos = 0

    def read(self) -> bytes:
        if self._buf is not None:
            chunk = bytes(self._buf[self._pos:self._pos + FRAME_BYTES])
            self._pos += FRAME_BYTES
        else:
            chunk = self._stream.read(FRAME_BYTES)
        if len(chunk) < FRAME_BYTES:
            return b""
        return chunk


class FFmpegPCMAudio(PCMAudio):
    """Any file ffmpeg can read (needs ``ffmpeg`` on PATH), decoded by the Rust SDK."""

    def __init__(self, source: str, *, executable: str = "ffmpeg", before_options: Optional[str] = None,
                 options: Optional[str] = None, **ignored: Any):
        super().__init__(b"")
        self.source = str(source)
        self._loaded = False

    async def load(self) -> None:
        if not self._loaded:
            self._buf = await _native().decode_with_ffmpeg(self.source)
            self._pos = 0
            self._loaded = True


FFmpegOpusAudio = FFmpegPCMAudio


class PCMVolumeTransformer(AudioSource):
    def __init__(self, original: AudioSource, volume: float = 1.0):
        self.original = original
        self.volume = volume

    async def load(self) -> None:
        await self.original.load()

    def read(self) -> bytes:
        import array

        data = self.original.read()
        if not data or self.volume == 1.0:
            return data
        a = array.array("h", data)
        for i, s in enumerate(a):
            a[i] = max(-32768, min(32767, int(s * self.volume)))
        return a.tobytes()

    def cleanup(self) -> None:
        self.original.cleanup()


class Speech:
    """One 20 ms frame one person said."""

    __slots__ = ("_native", "npub", "pcm")

    def __init__(self, native_speech: Any):
        self._native = native_speech
        self.npub: Optional[str] = native_speech.npub
        self.pcm: bytes = native_speech.pcm

    def __repr__(self) -> str:
        return f"<Speech npub={self.npub!r} bytes={len(self.pcm)}>"


class Utterances:
    """Groups frames into what each person said, one clip per pause."""

    def __init__(self, *, pause: Optional[float] = None, quiet_below: Optional[float] = None, longest: Optional[float] = None):
        self._inner = _native().NativeUtterances(pause, quiet_below, longest)

    def push(self, speech: Speech) -> Optional[Tuple[Optional[str], bytes]]:
        """Feed a frame; returns ``(npub, pcm)`` when someone finished a sentence."""
        return self._inner.push(speech._native)

    def flush(self) -> List[Tuple[Optional[str], bytes]]:
        return self._inner.flush()


class Transcriber:
    """Speech-to-text with whisper.cpp. Needs a build with the ``whisper`` feature and a model file."""

    def __init__(self, model: str, *, language: Optional[str] = None):
        n = _native()
        if not hasattr(n, "NativeTranscriber"):
            raise RuntimeError("this build has no whisper support (rebuild with the `whisper` feature, see README)")
        self._inner = n.NativeTranscriber(str(model), language)

    async def transcribe(self, pcm: bytes) -> str:
        return await self._inner.transcribe(pcm)


class VoiceProtocol:
    def __init__(self, client: "Client", channel: "VoiceChannel"):
        self.client = client
        self.channel = channel


class VoiceClient(VoiceProtocol):
    """The bot's connection to a voice Channel (``await voice_channel.connect()``)."""

    def __init__(self, client: "Client", channel: "VoiceChannel", native_call: Any):
        super().__init__(client, channel)
        self._call = native_call
        self._player: Optional[asyncio.Task] = None
        self._paused = asyncio.Event()
        self._paused.set()
        self.source: Optional[AudioSource] = None

    @property
    def guild(self):
        return self.channel.community

    community = guild

    @property
    def user(self):
        return self.client.user

    @property
    def latency(self) -> float:
        return 0.0

    average_latency = latency

    def is_connected(self) -> bool:
        return not self._call.ended()

    def is_playing(self) -> bool:
        return self._player is not None and not self._player.done() and self._paused.is_set()

    def is_paused(self) -> bool:
        return self._player is not None and not self._player.done() and not self._paused.is_set()

    @property
    def connected_peers(self) -> int:
        return self._call.connected()

    @property
    def moved_to(self) -> Optional[str]:
        return self._call.moved_to()

    @property
    def state(self) -> Optional[Dict[str, Any]]:
        return self._call.state()

    @property
    def queued(self) -> float:
        """Seconds of audio still queued to play."""
        return self._call.queued()

    # -- speaking -------------------------------------------------------------------------

    def say(self, pcm: bytes) -> bool:
        """Queue raw PCM to play (returns at once)."""
        return self._call.say(pcm)

    async def say_and_wait(self, pcm: bytes) -> bool:
        return await self._call.say_and_wait(pcm)

    async def finished(self) -> bool:
        """Wait until everything queued has played."""
        return await self._call.finished()

    def hush(self) -> None:
        """Stop talking now (drop the queue)."""
        self._call.hush()

    def play(self, source: AudioSource, *, after: Optional[Callable[[Optional[Exception]], Any]] = None,
             application: str = "audio", bitrate: int = 128, fec: bool = True, expected_packet_loss: float = 0.15,
             bandwidth: str = "full", signal_type: str = "auto") -> None:
        """Play an :class:`AudioSource` (discord.py signature)."""
        if self.is_playing():
            from .errors import ClientException

            raise ClientException("Already playing audio.")
        self.source = source

        async def runner() -> None:
            error: Optional[Exception] = None
            try:
                await source.load()
                while self.is_connected():
                    await self._paused.wait()
                    chunk: List[bytes] = []
                    for _ in range(25):  # half a second per push keeps latency and overhead low
                        frame = source.read()
                        if not frame:
                            break
                        chunk.append(frame)
                    if not chunk:
                        break
                    self._call.say(b"".join(chunk))
                    while self._call.queued() > 0.6:
                        await asyncio.sleep(0.1)
                await self._call.finished()
            except asyncio.CancelledError:
                self._call.hush()
            except Exception as e:  # pragma: no cover
                error = e
                _log.exception("audio player failed")
            finally:
                source.cleanup()
                if after is not None:
                    try:
                        r = after(error)
                        if asyncio.iscoroutine(r):
                            await r
                    except Exception:
                        _log.exception("after callback failed")

        self._player = asyncio.ensure_future(runner())

    def pause(self) -> None:
        self._paused.clear()
        self._call.hush()

    def resume(self) -> None:
        self._paused.set()

    def stop(self) -> None:
        if self._player is not None:
            self._player.cancel()
        self._call.hush()

    # -- listening ------------------------------------------------------------------------

    async def listen(self) -> AsyncIterator[Speech]:
        """``async for speech in vc.listen():`` every frame anyone says (``speech.npub``, ``speech.pcm``)."""
        while True:
            s = await self._call.listen()
            if s is None:
                return
            yield Speech(s)

    async def utterances(self, **opts: Any) -> AsyncIterator[Tuple[Any, bytes]]:
        """``async for member, pcm in vc.utterances():`` one clip per sentence, per speaker."""
        u = Utterances(**opts)
        async for speech in self.listen():
            done = u.push(speech)
            if done is not None:
                npub, pcm = done
                yield (self.channel.community._member(npub) if npub else None), pcm
        for npub, pcm in u.flush():
            yield (self.channel.community._member(npub) if npub else None), pcm

    # -- state ----------------------------------------------------------------------------

    def mute(self, on: bool = True) -> None:
        self._call.set_muted(on)

    def deafen(self, on: bool = True) -> None:
        self._call.set_deafened(on)

    async def disconnect(self, *, force: bool = False) -> None:
        self.stop()
        await self._call.leave()
        self.client._connection.voice_clients.pop(self.channel.community.id, None)

    async def move_to(self, channel: "VoiceChannel", **ignored: Any) -> None:
        await self.disconnect()
        new = await channel.connect()
        self.channel, self._call = new.channel, new._call

    def __repr__(self) -> str:
        return f"<VoiceClient channel={self.channel.name!r} connected={self.is_connected()}>"
