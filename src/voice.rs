//! Voice Channels: 48 kHz mono 16-bit PCM in and out. PCM crosses as little-endian `bytes`.

use std::sync::Arc;

use pyo3::prelude::*;
use vector_sdk::voice::{Speech, Utterance, Utterances};
use vector_sdk::VoiceCall;

use crate::convert::{bytes_to_pcm, err, json_of, pcm_to_bytes, Bytes, Json};

macro_rules! fut {
    ($py:ident, $($body:tt)*) => {
        pyo3_async_runtimes::tokio::future_into_py($py, async move { $($body)* })
    };
}

/// A bot's place in a voice Channel's call.
#[pyclass(module = "vector._native")]
pub struct NativeVoiceCall {
    call: Arc<VoiceCall>,
}

impl NativeVoiceCall {
    pub fn new(call: VoiceCall) -> Self {
        NativeVoiceCall { call: Arc::new(call) }
    }
}

/// One 20 ms frame one speaker said.
#[pyclass(module = "vector._native")]
#[derive(Clone)]
pub struct NativeSpeech {
    inner: Speech,
}

#[pymethods]
impl NativeSpeech {
    #[getter]
    fn npub(&self) -> Option<String> {
        self.inner.npub.clone()
    }
    #[getter]
    fn pcm(&self) -> Bytes {
        Bytes(pcm_to_bytes(&self.inner.pcm))
    }
    #[getter]
    fn samples(&self) -> usize {
        self.inner.pcm.len()
    }
}

#[pymethods]
impl NativeVoiceCall {
    #[getter]
    fn channel_id(&self) -> String {
        self.call.channel_id().to_string()
    }

    /// The next frame anyone said, or `None` when the call ends.
    fn listen<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let call = self.call.clone();
        fut!(py, Ok(call.listen().await.map(|s| NativeSpeech { inner: s })))
    }

    /// Queue PCM to play. False once the call has ended.
    fn say(&self, pcm: &[u8]) -> bool {
        self.call.say(&bytes_to_pcm(pcm))
    }

    fn say_and_wait<'py>(&self, py: Python<'py>, pcm: &[u8]) -> PyResult<Bound<'py, PyAny>> {
        let call = self.call.clone();
        let pcm = bytes_to_pcm(pcm);
        fut!(py, Ok(call.say_and_wait(&pcm).await))
    }

    fn finished<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let call = self.call.clone();
        fut!(py, Ok(call.finished().await))
    }

    fn ended(&self) -> bool {
        self.call.ended()
    }

    /// Seconds of audio still queued.
    fn queued(&self) -> f64 {
        self.call.queued().as_secs_f64()
    }

    /// Drop whatever is queued (stop talking now).
    fn hush(&self) {
        self.call.hush()
    }

    fn connected(&self) -> usize {
        self.call.connected()
    }

    fn moved_to(&self) -> Option<String> {
        self.call.moved_to()
    }

    fn state(&self) -> Option<Json> {
        self.call.state().map(|s| json_of(&s))
    }

    fn set_muted(&self, on: bool) -> PyResult<()> {
        self.call.set_muted(on).map_err(err)
    }

    fn set_deafened(&self, on: bool) -> PyResult<()> {
        self.call.set_deafened(on).map_err(err)
    }

    fn leave<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let call = self.call.clone();
        fut!(py, {
            call.hush();
            if !call.ended() {
                vector_sdk::vector_core::calls::voice::leave_channel(call.channel_id()).await;
            }
            Ok(())
        })
    }
}

fn utterance_py(u: Utterance) -> (Option<String>, Bytes) {
    (u.npub, Bytes(pcm_to_bytes(&u.pcm)))
}

/// Cuts a call's frames into what each person said, one clip per pause.
#[pyclass(module = "vector._native")]
pub struct NativeUtterances {
    inner: std::sync::Mutex<Utterances>,
}

#[pymethods]
impl NativeUtterances {
    #[new]
    #[pyo3(signature = (pause=None, quiet_below=None, longest=None))]
    fn new(pause: Option<f64>, quiet_below: Option<f32>, longest: Option<f64>) -> Self {
        let mut u = Utterances::new();
        if let Some(p) = pause {
            u = u.pause(std::time::Duration::from_secs_f64(p));
        }
        if let Some(q) = quiet_below {
            u = u.quiet_below(q);
        }
        if let Some(l) = longest {
            u = u.longest(std::time::Duration::from_secs_f64(l));
        }
        NativeUtterances { inner: std::sync::Mutex::new(u) }
    }

    /// Feed a frame; returns `(npub, pcm)` when someone finished a sentence.
    fn push(&self, speech: &NativeSpeech) -> Option<(Option<String>, Bytes)> {
        self.inner.lock().unwrap().push(speech.inner.clone()).map(utterance_py)
    }

    fn flush(&self) -> Vec<(Option<String>, Bytes)> {
        self.inner.lock().unwrap().flush().into_iter().map(utterance_py).collect()
    }
}

/// A sine tone as PCM bytes (handy for testing a call).
#[pyfunction]
pub fn tone(hz: f32, ms: u32) -> Bytes {
    Bytes(pcm_to_bytes(&vector_sdk::voice::tone(hz, ms)))
}

/// Loudness of a PCM buffer, 0.0–1.0.
#[pyfunction]
pub fn level(pcm: &[u8]) -> f32 {
    vector_sdk::voice::level(&bytes_to_pcm(pcm))
}

/// Decode any audio file ffmpeg can read into call-ready PCM bytes (needs `ffmpeg` on PATH).
#[pyfunction]
pub fn decode_with_ffmpeg(py: Python<'_>, path: String) -> PyResult<Bound<'_, PyAny>> {
    fut!(py, vector_sdk::voice::decode_with_ffmpeg(path).await.map(|p| Bytes(pcm_to_bytes(&p))).map_err(err))
}

pub const SAMPLE_RATE: u32 = vector_sdk::voice::SAMPLE_RATE;
pub const FRAME: usize = vector_sdk::voice::FRAME;

/// Speech-to-text with whisper.cpp (the `whisper` build feature).
#[cfg(feature = "whisper")]
#[pyclass(module = "vector._native")]
pub struct NativeTranscriber {
    inner: Arc<vector_sdk::voice::Transcriber>,
}

#[cfg(feature = "whisper")]
#[pymethods]
impl NativeTranscriber {
    #[new]
    #[pyo3(signature = (model, language=None))]
    fn new(model: String, language: Option<String>) -> PyResult<Self> {
        let mut t = vector_sdk::voice::Transcriber::load(model).map_err(err)?;
        if let Some(l) = language {
            t = t.language(&l);
        }
        Ok(NativeTranscriber { inner: Arc::new(t) })
    }

    fn transcribe<'py>(&self, py: Python<'py>, pcm: &[u8]) -> PyResult<Bound<'py, PyAny>> {
        let t = self.inner.clone();
        let pcm = bytes_to_pcm(pcm);
        fut!(py, t.transcribe(&pcm).await.map_err(err))
    }
}
