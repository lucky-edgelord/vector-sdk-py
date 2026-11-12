//! `NativeBot`: the whole `vector_sdk::VectorBot` surface as one flat Python class.
//!
//! The Python layer (`vector.Client`, `vector.Channel`, `vector.Community`, …) is object-
//! oriented; underneath, every call lands here addressed by ids. Async SDK calls return Python
//! awaitables driven by a shared tokio runtime (`pyo3-async-runtimes`).
//!
//! Inbound events are queued: the SDK's listener pushes each `BotEvent` (and each slash command
//! invocation, and each Mini App session) onto a channel that Python drains with `next_event()`.
//! No Python code ever runs on a tokio thread, so there are no GIL or event-loop surprises.

use std::sync::Arc;
use std::time::Duration;

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;
use serde_json::{json, Map, Value};
use tokio::sync::mpsc::{unbounded_channel, UnboundedReceiver, UnboundedSender};
use tokio::sync::Mutex;
use vector_sdk::{
    Attachment, Channel, Cursor, InvitePolicy, NewChannel, NewCommunity, Overwrite, Permissions, PostOptions, RoleSpec,
    VectorBot,
};

use crate::convert::{audit_json, err, event_json, incoming_json, json_of, other, Bytes, Json};

macro_rules! fut {
    ($py:ident, $($body:tt)*) => {
        pyo3_async_runtimes::tokio::future_into_py($py, async move { $($body)* })
    };
}

/// One item on the inbound queue.
pub enum Inbound {
    Event(Value),
    #[cfg(feature = "xdc")]
    XdcSession { handler: u64, session: vector_sdk::XdcSession },
}

impl<'py> IntoPyObject<'py> for Inbound {
    type Target = PyAny;
    type Output = Bound<'py, PyAny>;
    type Error = PyErr;

    fn into_pyobject(self, py: Python<'py>) -> Result<Self::Output, Self::Error> {
        match self {
            Inbound::Event(v) => crate::convert::value_to_py(py, &v),
            #[cfg(feature = "xdc")]
            Inbound::XdcSession { handler, session } => {
                let d = PyDict::new(py);
                d.set_item("type", "xdc_session")?;
                d.set_item("handler", handler)?;
                d.set_item("app", crate::convert::value_to_py(py, &crate::xdc::app_json(session.app()))?)?;
                d.set_item("session", Py::new(py, crate::xdc::NativeXdcSession::new(session))?)?;
                Ok(d.into_any())
            }
        }
    }
}

#[pyclass(module = "vector._native")]
pub struct NativeBot {
    pub(crate) bot: VectorBot,
    tx: UnboundedSender<Inbound>,
    rx: Arc<Mutex<UnboundedReceiver<Inbound>>>,
    shutdown: Arc<tokio::sync::Notify>,
    #[cfg(feature = "xdc")]
    next_xdc_handler: std::sync::atomic::AtomicU64,
}

fn post_opts(reply_to: Option<String>, expires_in: Option<u64>, to_bot: Option<String>, caption: Option<String>, compress: bool) -> PostOptions {
    let mut o = PostOptions::default().compress(compress);
    if let Some(r) = reply_to {
        o = o.reply_to(r);
    }
    if let Some(s) = expires_in {
        o = o.expires_in(s);
    }
    if let Some(b) = to_bot {
        o = o.to_bot(b);
    }
    if let Some(c) = caption {
        o = o.caption(c);
    }
    o
}

fn cursor(s: Option<String>) -> PyResult<Option<Cursor>> {
    s.map(|s| s.parse::<Cursor>().map_err(PyValueError::new_err)).transpose()
}

fn role_spec(
    name: Option<String>,
    color: Option<u32>,
    permissions: Option<u64>,
    channel_id: Option<String>,
    shown: Option<bool>,
    mentionable: Option<bool>,
) -> RoleSpec {
    let mut s = RoleSpec::unchanged();
    if let Some(n) = name {
        s = s.name(n);
    }
    if let Some(c) = color {
        s = s.color(c);
    }
    if let Some(p) = permissions {
        s = s.permissions(Permissions(p));
    }
    if let Some(c) = channel_id {
        s = s.in_channel(c);
    }
    match shown {
        Some(true) => s = s.shown(),
        Some(false) => s = s.hidden(),
        None => {}
    }
    if let Some(m) = mentionable {
        s = s.mentionable(m);
    }
    s
}

impl NativeBot {
    fn new(bot: VectorBot) -> Self {
        let (tx, rx) = unbounded_channel();
        NativeBot {
            bot,
            tx,
            rx: Arc::new(Mutex::new(rx)),
            shutdown: Arc::new(tokio::sync::Notify::new()),
            #[cfg(feature = "xdc")]
            next_xdc_handler: std::sync::atomic::AtomicU64::new(1),
        }
    }

    /// A channel handle: `kind` "dm" / "community" forces it, `None` auto-detects like the SDK.
    fn ch(&self, id: String, kind: Option<&str>) -> Channel {
        match kind {
            Some("dm") => self.bot.dm(id),
            Some("community") => self.bot.community(String::new()).channel(id),
            _ => self.bot.channel(id),
        }
    }

    fn overwrite(&self, community_id: &str, target_kind: &str, target_id: Option<String>, allow: u64, deny: u64) -> PyResult<Overwrite> {
        let base = match target_kind {
            "everyone" => Overwrite::everyone(),
            "role" => Overwrite::role(&self.bot.community(community_id.to_string()).role(target_id.ok_or_else(|| other("role overwrite needs a role id"))?)),
            "member" => Overwrite::member(target_id.ok_or_else(|| other("member overwrite needs an npub"))?),
            k => return Err(PyValueError::new_err(format!("unknown overwrite target {k:?}"))),
        };
        Ok(base.allow(Permissions(allow)).deny(Permissions(deny)))
    }
}

/// The manifest rules (`vector_core::bot_interface`), checked up front so a bad spec is a clean
/// `ValueError` instead of an SDK panic.
fn validate_command(name: &str, description: &str, args: &[(String, String, String, bool, Vec<String>)]) -> Result<(), String> {
    fn slug(s: &str) -> bool {
        !s.is_empty() && s.len() <= 32 && s.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_' || b == b'-')
    }
    if !slug(name) {
        return Err(format!("bad command name {name:?} (lowercase a-z, 0-9, '_' or '-', at most 32)"));
    }
    if description.len() > 200 {
        return Err("description longer than 200 bytes".into());
    }
    if args.len() > 8 {
        return Err("more than 8 arguments".into());
    }
    let mut seen = std::collections::HashSet::new();
    let mut optional_seen = false;
    for (n, t, d, required, choices) in args {
        if !slug(n) {
            return Err(format!("bad argument name {n:?}"));
        }
        if !seen.insert(n) {
            return Err(format!("duplicate argument {n:?}"));
        }
        if d.len() > 200 {
            return Err(format!("description of {n:?} longer than 200 bytes"));
        }
        if *required && optional_seen {
            return Err(format!("required argument {n:?} after an optional one"));
        }
        optional_seen |= !required;
        if t == "choice" {
            if choices.is_empty() || choices.len() > 32 || choices.iter().any(|c| c.is_empty() || c.len() > 32) {
                return Err(format!("choice argument {n:?} needs 1-32 choices of 1-32 bytes"));
            }
        } else if !choices.is_empty() {
            return Err(format!("choices on non-choice argument {n:?}"));
        }
    }
    Ok(())
}

fn target(kind: &str, id: Option<String>) -> PyResult<vector_sdk::OverwriteTarget> {
    use vector_sdk::OverwriteTarget as T;
    Ok(match kind {
        "everyone" => T::Everyone,
        "role" => T::Role(id.ok_or_else(|| other("needs a role id"))?),
        "member" => T::Member(id.ok_or_else(|| other("needs an npub"))?),
        k => return Err(PyValueError::new_err(format!("unknown overwrite target {k:?}"))),
    })
}

#[pymethods]
impl NativeBot {
    // ======================================================================================
    // Construction & lifecycle
    // ======================================================================================

    /// Build (log in) a bot. Every argument mirrors a `VectorBotBuilder` method.
    #[staticmethod]
    #[pyo3(signature = (*, nsec=None, mnemonic=None, password=None, data_dir=None, invite_policy="manual".to_string(),
        whitelist=None, catch_up="inline".to_string(), clearnet=false, tor=false, tor_bridges=None, i2p=false,
        i2p_sam_port=None, xdc_download_limit=None))]
    #[allow(clippy::too_many_arguments, unused_variables, unused_mut)]
    fn build<'py>(
        py: Python<'py>,
        nsec: Option<String>,
        mnemonic: Option<String>,
        password: Option<String>,
        data_dir: Option<String>,
        invite_policy: String,
        whitelist: Option<Vec<String>>,
        catch_up: String,
        clearnet: bool,
        tor: bool,
        tor_bridges: Option<Vec<String>>,
        i2p: bool,
        i2p_sam_port: Option<u16>,
        xdc_download_limit: Option<usize>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let mut b = VectorBot::builder();
        if let Some(k) = nsec {
            b = b.nsec(k);
        } else if let Some(m) = mnemonic {
            b = b.mnemonic(m);
        }
        if let Some(p) = password {
            b = b.password(p);
        }
        if let Some(d) = data_dir {
            b = b.data_dir(d);
        }
        b = match (invite_policy.as_str(), whitelist) {
            (_, Some(list)) if !list.is_empty() => b.whitelist(list),
            ("public", _) => b.public(),
            ("manual", _) => b.invite_policy(InvitePolicy::Manual),
            (p, _) => return Err(PyValueError::new_err(format!("invite_policy must be 'manual' or 'public', not {p:?}"))),
        };
        b = b.catch_up(match catch_up.as_str() {
            "inline" => vector_sdk::CatchUp::Inline,
            "external" => vector_sdk::CatchUp::External,
            c => return Err(PyValueError::new_err(format!("catch_up must be 'inline' or 'external', not {c:?}"))),
        });
        if clearnet {
            b = b.clearnet();
        }
        if tor {
            #[cfg(feature = "tor")]
            {
                b = b.tor();
                if let Some(br) = tor_bridges {
                    b = b.tor_bridges(br);
                }
            }
            #[cfg(not(feature = "tor"))]
            return Err(other("this build has no Tor support: reinstall with the `tor` feature (see README)"));
        }
        if i2p {
            #[cfg(feature = "i2p")]
            {
                let mut o = vector_sdk::I2pOptions::default();
                if let Some(p) = i2p_sam_port {
                    o.sam_port = p;
                }
                b = b.i2p_with(o);
            }
            #[cfg(not(feature = "i2p"))]
            return Err(other("this build has no I2P support: reinstall with the `i2p` feature (see README)"));
        }
        #[cfg(feature = "xdc")]
        if let Some(n) = xdc_download_limit {
            b = b.xdc_download_limit(n);
        }
        fut!(py, {
            let bot = b.build().await.map_err(err)?;
            Ok(NativeBot::new(bot))
        })
    }

    /// Mint a fresh `nsec1…` secret key.
    #[staticmethod]
    fn generate_nsec() -> PyResult<String> {
        VectorBot::generate_nsec().map_err(err)
    }

    /// Which optional features this build has.
    #[staticmethod]
    fn features() -> Vec<&'static str> {
        let mut f = vec![];
        if cfg!(feature = "voice") {
            f.push("voice");
        }
        if cfg!(feature = "xdc") {
            f.push("xdc");
        }
        if cfg!(feature = "whisper") {
            f.push("whisper");
        }
        if cfg!(feature = "tor") {
            f.push("tor");
        }
        if cfg!(feature = "i2p") {
            f.push("i2p");
        }
        f
    }

    #[getter]
    fn npub(&self) -> String {
        self.bot.npub().to_string()
    }

    fn subscription_ready(&self) -> bool {
        self.bot.subscription_ready()
    }

    /// Start the SDK listener. Resolves when the bot disconnects. Events go to `next_event()`.
    fn start<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        let tx = self.tx.clone();
        let shutdown = self.shutdown.clone();
        fut!(py, {
            let etx = tx.clone();
            // Like `VectorBot::run`: the listener ends when its future is dropped, so race it
            // against `stop()`/`logout()`.
            let res = tokio::select! {
                r = bot.on_event(move |_bot, ev| {
                    let tx = etx.clone();
                    async move {
                        let _ = tx.send(Inbound::Event(event_json(&ev)));
                    }
                }) => r,
                _ = shutdown.notified() => Ok(()),
            };
            let _ = tx.send(Inbound::Event(json!({"type": "disconnect", "error": res.as_ref().err().map(|e| e.to_string())})));
            res.map_err(err)
        })
    }

    /// The next inbound event as a dict, or `None` once the queue is closed.
    fn next_event<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let rx = self.rx.clone();
        fut!(py, Ok(rx.lock().await.recv().await))
    }

    /// Stop the listener started by `start()` (without logging out).
    fn stop(&self) {
        self.shutdown.notify_one();
    }

    /// Stop listening, disconnect from relays and close the database.
    fn logout<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        self.shutdown.notify_one();
        let bot = self.bot.clone();
        fut!(py, {
            bot.logout().await;
            Ok(())
        })
    }

    // ======================================================================================
    // Slash commands
    // ======================================================================================

    /// Register a native slash command. `args` is a list of
    /// `(name, type, description, required, choices)` with type one of
    /// `string|int|number|flag|user|choice`. Invocations arrive as `{"type": "command", …}` events.
    fn register_command(&self, name: String, description: String, args: Vec<(String, String, String, bool, Vec<String>)>) -> PyResult<()> {
        validate_command(&name, &description, &args).map_err(|e| PyValueError::new_err(format!("invalid command /{name}: {e}")))?;
        let mut b = self.bot.command(&name, &description);
        let mut kinds = Vec::new();
        for (n, t, d, req, choices) in &args {
            b = match t.as_str() {
                "string" => b.string(n, d, *req),
                "int" => b.int(n, d, *req),
                "number" => b.number(n, d, *req),
                "flag" => b.flag(n, d, *req),
                "user" => b.user(n, d, *req),
                "choice" => b.choice(n, d, choices.clone(), *req),
                other => return Err(PyValueError::new_err(format!("unknown argument type {other:?}"))),
            };
            kinds.push((n.clone(), t.clone()));
        }
        let tx = self.tx.clone();
        let cmd = name.clone();
        let handler = move |ctx: vector_sdk::CommandCtx| {
            let tx = tx.clone();
            let kinds = kinds.clone();
            let cmd = cmd.clone();
            async move {
                let mut a = Map::new();
                for (n, t) in kinds {
                    let v = match t.as_str() {
                        "int" => ctx.int(&n).map(Value::from),
                        "number" => ctx.number(&n).map(Value::from),
                        "flag" => ctx.flag(&n).map(Value::from),
                        _ => ctx.str(&n).map(Value::from),
                    };
                    a.insert(n, v.unwrap_or(Value::Null));
                }
                let _ = tx.send(Inbound::Event(json!({
                    "type": "command", "name": cmd, "args": a, "message": incoming_json(&ctx.msg),
                })));
            }
        };
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| b.run(handler)))
            .map_err(|p| {
                let why = p.downcast_ref::<String>().cloned().or_else(|| p.downcast_ref::<&str>().map(|s| s.to_string())).unwrap_or_default();
                PyValueError::new_err(format!("invalid command /{name}: {why}"))
            })
    }

    // ======================================================================================
    // Invites, communities, joining
    // ======================================================================================

    fn pending_invites(&self) -> PyResult<Json> {
        self.bot.pending_invites().map(|v| json_of(&v)).map_err(err)
    }

    fn accept_invite<'py>(&self, py: Python<'py>, community_id: String) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, bot.accept_invite(&community_id).await.map(Json).map_err(err))
    }

    fn process_pending_invites<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, {
            bot.process_pending_invites().await;
            Ok(())
        })
    }

    fn communities<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, Ok(bot.communities().await.iter().map(|c| c.id().to_string()).collect::<Vec<_>>()))
    }

    #[pyo3(signature = (name, description=None, first_channel=None, relays=None))]
    fn create_community<'py>(&self, py: Python<'py>, name: String, description: Option<String>, first_channel: Option<String>, relays: Option<Vec<String>>) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        let mut o = NewCommunity::default();
        if let Some(d) = description {
            o = o.description(d);
        }
        if let Some(f) = first_channel {
            o = o.first_channel(f);
        }
        if let Some(r) = relays {
            o = o.relays(r);
        }
        fut!(py, bot.create_community(&name, o).await.map(|c| c.id().to_string()).map_err(err))
    }

    fn join<'py>(&self, py: Python<'py>, invite_url: String) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, bot.join(&invite_url).await.map(|c| c.id().to_string()).map_err(err))
    }

    fn preview_link<'py>(&self, py: Python<'py>, invite_url: String) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, bot.preview_link(&invite_url).await.map(|p| json_of(&p)).map_err(err))
    }

    // ======================================================================================
    // Messages & history
    // ======================================================================================

    fn message<'py>(&self, py: Python<'py>, message_id: String) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, Ok(bot.message(&message_id).await.map(|m| Json(incoming_json(&m)))))
    }

    fn messages_with_attachment<'py>(&self, py: Python<'py>, content_hash: String) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, Ok(Json(Value::Array(bot.messages_with_attachment(&content_hash).await.iter().map(incoming_json).collect()))))
    }

    #[pyo3(signature = (since_days=None))]
    fn sync_dms<'py>(&self, py: Python<'py>, since_days: Option<u64>) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, bot.sync_dms(since_days).await.map_err(err))
    }

    fn sync_communities<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, bot.sync_communities().await.map_err(err))
    }

    // ======================================================================================
    // Profiles
    // ======================================================================================

    fn fetch_profile<'py>(&self, py: Python<'py>, npub: String) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, Ok(bot.fetch_profile(&npub).await.map(|p| json_of(&p))))
    }

    fn cached_profile<'py>(&self, py: Python<'py>, npub: String) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, Ok(bot.cached_profile(&npub).await.map(|p| json_of(&p))))
    }

    fn update_profile<'py>(&self, py: Python<'py>, name: String, avatar: String, banner: String, about: String) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, bot.update_profile(&name, &avatar, &banner, &about).await.map_err(err))
    }

    fn set_status<'py>(&self, py: Python<'py>, status: String) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, bot.set_status(&status).await.map_err(err))
    }

    fn block<'py>(&self, py: Python<'py>, npub: String) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, bot.block(&npub).await.map_err(err))
    }

    fn unblock<'py>(&self, py: Python<'py>, npub: String) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, bot.unblock(&npub).await.map_err(err))
    }

    fn set_local_nickname<'py>(&self, py: Python<'py>, npub: String, nickname: String) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, bot.set_nickname(&npub, &nickname).await.map_err(err))
    }

    fn blocked_users<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, Ok(json_of(&bot.blocked_users().await)))
    }

    fn upload_image<'py>(&self, py: Python<'py>, path: String) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, bot.upload_image(path).await.map_err(err))
    }

    // ======================================================================================
    // Custom emoji
    // ======================================================================================

    fn subscribe_emoji_pack<'py>(&self, py: Python<'py>, naddr: String) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, bot.subscribe_emoji_pack(&naddr).await.map(|p| json_of(&p)).map_err(err))
    }

    fn unsubscribe_emoji_pack<'py>(&self, py: Python<'py>, naddr: String) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, bot.unsubscribe_emoji_pack(&naddr).await.map_err(err))
    }

    fn emoji_packs(&self) -> PyResult<Json> {
        self.bot.emoji_packs().map(|p| json_of(&p)).map_err(err)
    }

    fn emojis(&self) -> Json {
        json_of(&self.bot.emojis())
    }

    fn refresh_emoji_packs<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, bot.refresh_emoji_packs().await.map(|p| json_of(&p)).map_err(err))
    }

    // ======================================================================================
    // Attachments (passed back as the JSON dict the event delivered)
    // ======================================================================================

    #[pyo3(signature = (attachment_json, author_npub=None))]
    fn download_attachment<'py>(&self, py: Python<'py>, attachment_json: String, author_npub: Option<String>) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        let att: Attachment = serde_json::from_str(&attachment_json).map_err(|e| PyValueError::new_err(format!("bad attachment: {e}")))?;
        fut!(py, bot.download_attachment_from(&att, author_npub.as_deref()).await.map(Bytes).map_err(err))
    }

    // ======================================================================================
    // Channels (DMs and Community channels alike)
    // ======================================================================================

    /// "dm" or "community", as the SDK would auto-detect `id`.
    fn channel_kind(&self, id: String) -> &'static str {
        if self.bot.channel(id).is_dm() { "dm" } else { "community" }
    }

    /// The Community id a channel belongs to, if any.
    #[pyo3(signature = (id, kind=None))]
    fn channel_community(&self, id: String, kind: Option<String>) -> Option<String> {
        self.ch(id, kind.as_deref()).community().map(|c| c.id().to_string())
    }

    #[pyo3(signature = (id, kind, text, reply_to=None, expires_in=None, to_bot=None))]
    fn channel_send<'py>(&self, py: Python<'py>, id: String, kind: Option<String>, text: String, reply_to: Option<String>, expires_in: Option<u64>, to_bot: Option<String>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, kind.as_deref());
        fut!(py, {
            if reply_to.is_none() && expires_in.is_none() && to_bot.is_none() {
                c.send(&text).await.map_err(err)
            } else {
                c.post(&text, post_opts(reply_to, expires_in, to_bot, None, true)).await.map_err(err)
            }
        })
    }

    #[pyo3(signature = (id, kind, data, filename, caption=None, reply_to=None, expires_in=None, compress=true))]
    #[allow(clippy::too_many_arguments)]
    fn channel_send_bytes<'py>(&self, py: Python<'py>, id: String, kind: Option<String>, data: &[u8], filename: String, caption: Option<String>, reply_to: Option<String>, expires_in: Option<u64>, compress: bool) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, kind.as_deref());
        let data = data.to_vec();
        fut!(py, c.send_bytes(data, &filename, post_opts(reply_to, expires_in, None, caption, compress)).await.map_err(err))
    }

    #[pyo3(signature = (id, kind, path, caption=None, reply_to=None, expires_in=None, compress=true))]
    #[allow(clippy::too_many_arguments)]
    fn channel_send_file<'py>(&self, py: Python<'py>, id: String, kind: Option<String>, path: String, caption: Option<String>, reply_to: Option<String>, expires_in: Option<u64>, compress: bool) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, kind.as_deref());
        fut!(py, c.send_file_with(path, post_opts(reply_to, expires_in, None, caption, compress)).await.map_err(err))
    }

    #[pyo3(signature = (id, kind, message_id, emoji, image_url=None))]
    fn channel_react<'py>(&self, py: Python<'py>, id: String, kind: Option<String>, message_id: String, emoji: String, image_url: Option<String>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, kind.as_deref());
        fut!(py, match image_url {
            Some(url) => c.react_custom(&message_id, &emoji, &url).await.map_err(err),
            None => c.react(&message_id, &emoji).await.map_err(err),
        })
    }

    fn channel_unreact<'py>(&self, py: Python<'py>, id: String, kind: Option<String>, message_id: String, emoji: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, kind.as_deref());
        fut!(py, c.unreact(&message_id, &emoji).await.map_err(err))
    }

    fn channel_typing<'py>(&self, py: Python<'py>, id: String, kind: Option<String>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, kind.as_deref());
        fut!(py, c.typing().await.map_err(err))
    }

    fn channel_edit<'py>(&self, py: Python<'py>, id: String, kind: Option<String>, message_id: String, text: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, kind.as_deref());
        fut!(py, c.edit(&message_id, &text).await.map_err(err))
    }

    fn channel_delete_message<'py>(&self, py: Python<'py>, id: String, kind: Option<String>, message_id: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, kind.as_deref());
        fut!(py, c.delete(&message_id).await.map_err(err))
    }

    fn channel_hide<'py>(&self, py: Python<'py>, id: String, kind: Option<String>, message_id: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, kind.as_deref());
        fut!(py, c.hide(&message_id).await.map_err(err))
    }

    #[pyo3(signature = (id, kind, limit, before=None))]
    fn channel_history<'py>(&self, py: Python<'py>, id: String, kind: Option<String>, limit: usize, before: Option<String>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, kind.as_deref());
        let before = cursor(before)?;
        fut!(py, Ok(json_of(&match before {
            Some(cur) => c.history_before(&cur, limit).await,
            None => c.history(limit).await,
        })))
    }

    #[pyo3(signature = (id, max_events, before=None, since_ms=None))]
    fn channel_sync<'py>(&self, py: Python<'py>, id: String, max_events: usize, before: Option<String>, since_ms: Option<u64>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, Some("community"));
        let before = cursor(before)?;
        fut!(py, match (before, since_ms) {
            (Some(cur), _) => c.sync_before(&cur, max_events).await.map_err(err),
            (None, Some(s)) => c.sync_since(s, max_events).await.map_err(err),
            (None, None) => c.sync(max_events).await.map_err(err),
        })
    }

    fn channel_info(&self, id: String) -> PyResult<Json> {
        self.ch(id, Some("community")).info().map(|i| json_of(&i)).map_err(err)
    }

    fn channel_rename<'py>(&self, py: Python<'py>, id: String, name: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, Some("community"));
        fut!(py, c.rename(&name).await.map_err(err))
    }

    #[pyo3(signature = (id, topic=None))]
    fn channel_set_topic<'py>(&self, py: Python<'py>, id: String, topic: Option<String>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, Some("community"));
        fut!(py, c.set_topic(topic.as_deref()).await.map_err(err))
    }

    fn channel_set_view<'py>(&self, py: Python<'py>, id: String, view: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, Some("community"));
        fut!(py, c.set_view(&view).await.map_err(err))
    }

    fn channel_set_read_only<'py>(&self, py: Python<'py>, id: String, read_only: bool) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, Some("community"));
        fut!(py, c.set_read_only(read_only).await.map_err(err))
    }

    #[pyo3(signature = (id, category_id, index))]
    fn channel_move<'py>(&self, py: Python<'py>, id: String, category_id: Option<String>, index: usize) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, Some("community"));
        let cat = match (&category_id, c.community()) {
            (Some(k), Some(comm)) => Some(comm.category(k.clone())),
            (Some(_), None) => return Err(other("channel is not in a community this bot holds")),
            _ => None,
        };
        fut!(py, c.move_to(cat.as_ref(), index).await.map_err(err))
    }

    fn channel_overwrites(&self, id: String) -> PyResult<Json> {
        let o = self.ch(id, Some("community")).overwrites().map_err(err)?;
        Ok(Json(Value::Array(
            o.iter()
                .map(|o| json!({"target": serde_json::to_value(&o.target).unwrap_or(Value::Null), "allow": o.allow.0, "deny": o.deny.0}))
                .collect(),
        )))
    }

    #[pyo3(signature = (id, target_kind, target_id, allow, deny))]
    fn channel_set_overwrite<'py>(&self, py: Python<'py>, id: String, target_kind: String, target_id: Option<String>, allow: u64, deny: u64) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, Some("community"));
        let cid = c.community().map(|c| c.id().to_string()).unwrap_or_default();
        let ow = self.overwrite(&cid, &target_kind, target_id, allow, deny)?;
        fut!(py, c.set_overwrite(ow).await.map_err(err))
    }

    #[pyo3(signature = (id, target_kind, target_id=None))]
    fn channel_clear_overwrite<'py>(&self, py: Python<'py>, id: String, target_kind: String, target_id: Option<String>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, Some("community"));
        let t = target(&target_kind, target_id)?;
        fut!(py, c.clear_overwrite(t).await.map_err(err))
    }

    #[pyo3(signature = (id, category_id=None))]
    fn channel_sync_permissions<'py>(&self, py: Python<'py>, id: String, category_id: Option<String>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, Some("community"));
        let cat = category_id.and_then(|k| c.community().map(|comm| comm.category(k)));
        fut!(py, c.sync_permissions(cat.as_ref()).await.map_err(err))
    }

    fn channel_permissions_of(&self, id: String, npub: String) -> PyResult<u64> {
        self.ch(id, Some("community")).permissions_of(&npub).map(|p| p.0).map_err(err)
    }

    fn channel_pins(&self, id: String) -> PyResult<Json> {
        let pins = self.ch(id, Some("community")).pins().map_err(err)?;
        Ok(Json(Value::Array(
            pins.iter().map(|p| json!({"message_id": p.message_id, "author": p.author, "content": p.content, "at_ms": p.at_ms})).collect(),
        )))
    }

    fn channel_pin<'py>(&self, py: Python<'py>, id: String, message_id: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, Some("community"));
        fut!(py, c.pin(&message_id).await.map_err(err))
    }

    fn channel_unpin<'py>(&self, py: Python<'py>, id: String, message_id: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, Some("community"));
        fut!(py, c.unpin(&message_id).await.map_err(err))
    }

    // ======================================================================================
    // Communities
    // ======================================================================================

    fn community_name<'py>(&self, py: Python<'py>, community_id: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, Ok(c.name().await))
    }

    fn community_description(&self, community_id: String) -> Option<String> {
        self.bot.community(community_id).description()
    }

    fn community_owner(&self, community_id: String) -> Option<String> {
        self.bot.community(community_id).owner()
    }

    fn community_admins(&self, community_id: String) -> PyResult<Vec<String>> {
        self.bot.community(community_id).admins().map_err(err)
    }

    fn community_capabilities(&self, community_id: String) -> PyResult<Json> {
        self.bot.community(community_id).capabilities().map(Json).map_err(err)
    }

    fn community_is_dissolved<'py>(&self, py: Python<'py>, community_id: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, Ok(c.is_dissolved().await))
    }

    /// Every channel, including private ones not yet readable.
    fn community_channels<'py>(&self, py: Python<'py>, community_id: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, Ok(Json(Value::Array(
            c.channels().await.iter().map(|ch| json!({
                "channel_id": ch.id(), "name": ch.name(), "private": ch.is_private(), "readable": ch.is_readable(), "epoch": ch.epoch(),
            })).collect()
        ))))
    }

    fn community_channel_infos(&self, community_id: String) -> PyResult<Json> {
        self.bot.community(community_id).channel_infos().map(|v| json_of(&v)).map_err(err)
    }

    fn community_primary_channel(&self, community_id: String) -> Option<String> {
        self.bot.community(community_id).primary_channel().map(|c| c.id().to_string())
    }

    #[pyo3(signature = (community_id, name, private=false, category_id=None, view=None, topic=None))]
    #[allow(clippy::too_many_arguments)]
    fn community_create_channel<'py>(&self, py: Python<'py>, community_id: String, name: String, private: bool, category_id: Option<String>, view: Option<String>, topic: Option<String>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        let mut o = NewChannel::default();
        if private {
            o = o.private();
        }
        if let Some(k) = category_id {
            o = o.in_category(k);
        }
        if let Some(v) = view {
            o = o.view(v);
        }
        if let Some(t) = topic {
            o = o.topic(t);
        }
        fut!(py, c.create_channel_with(&name, o).await.map(|ch| ch.id().to_string()).map_err(err))
    }

    fn community_set_channel_private<'py>(&self, py: Python<'py>, community_id: String, channel_id: String, private: bool) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, c.set_channel_private(&channel_id, private).await.map_err(err))
    }

    fn community_delete_channel<'py>(&self, py: Python<'py>, community_id: String, channel_id: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, c.delete_channel(&channel_id).await.map_err(err))
    }

    fn community_grant_access<'py>(&self, py: Python<'py>, community_id: String, channel_id: String, npub: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, c.grant_access(&channel_id, &npub).await.map_err(err))
    }

    fn community_revoke_access<'py>(&self, py: Python<'py>, community_id: String, channel_id: String, npub: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, c.revoke_access(&channel_id, &npub).await.map_err(err))
    }

    fn community_channel_members(&self, community_id: String, channel_id: String) -> Vec<String> {
        self.bot.community(community_id).channel_members(&channel_id).iter().map(|m| m.npub().to_string()).collect()
    }

    fn community_channel_access(&self, community_id: String, channel_id: String) -> PyResult<Json> {
        self.bot.community(community_id).channel_access(&channel_id).map(Json).map_err(err)
    }

    fn community_members<'py>(&self, py: Python<'py>, community_id: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, Ok(c.members().await.iter().map(|m| m.npub().to_string()).collect::<Vec<_>>()))
    }

    fn community_banned(&self, community_id: String) -> Vec<String> {
        self.bot.community(community_id).banned()
    }

    fn community_ban_many<'py>(&self, py: Python<'py>, community_id: String, npubs: Vec<String>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, {
            let refs: Vec<&str> = npubs.iter().map(String::as_str).collect();
            c.ban_many(&refs).await.map_err(err)
        })
    }

    fn community_unban_many<'py>(&self, py: Python<'py>, community_id: String, npubs: Vec<String>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, {
            let refs: Vec<&str> = npubs.iter().map(String::as_str).collect();
            c.unban_many(&refs).await.map_err(err)
        })
    }

    #[pyo3(signature = (community_id, npubs, window_start_secs, cut_also=None))]
    fn community_contain_raid<'py>(&self, py: Python<'py>, community_id: String, npubs: Vec<String>, window_start_secs: u64, cut_also: Option<Vec<String>>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        let cut_also = cut_also.unwrap_or_default();
        fut!(py, {
            let refs: Vec<&str> = npubs.iter().map(String::as_str).collect();
            let cut: Vec<&str> = cut_also.iter().map(String::as_str).collect();
            c.contain_raid_with(&refs, window_start_secs, &cut).await.map(|r| json_of(&r)).map_err(err)
        })
    }

    fn community_raid_report(&self, community_id: String) -> PyResult<Json> {
        self.bot.community(community_id).raid_report().map(Json).map_err(err)
    }

    fn community_invite<'py>(&self, py: Python<'py>, community_id: String, npub: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, c.invite(&npub).await.map_err(err))
    }

    #[pyo3(signature = (community_id, expires_at_ms=None, label=None))]
    fn community_create_invite<'py>(&self, py: Python<'py>, community_id: String, expires_at_ms: Option<u64>, label: Option<String>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, c.create_invite_with(expires_at_ms, label).await.map_err(err))
    }

    fn community_invite_links(&self, community_id: String) -> PyResult<Json> {
        self.bot.community(community_id).invite_links().map(|v| json_of(&v)).map_err(err)
    }

    fn community_revoke_invite<'py>(&self, py: Python<'py>, community_id: String, token: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, c.revoke_invite(&token).await.map_err(err))
    }

    fn community_revoke_all_invites<'py>(&self, py: Python<'py>, community_id: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, c.revoke_all_invites().await.map_err(err))
    }

    #[pyo3(signature = (community_id, name=None, description=None))]
    fn community_edit<'py>(&self, py: Python<'py>, community_id: String, name: Option<String>, description: Option<String>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, c.edit(name.as_deref(), description.as_deref()).await.map_err(err))
    }

    fn community_leave<'py>(&self, py: Python<'py>, community_id: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, c.leave().await.map_err(err))
    }

    fn community_dissolve<'py>(&self, py: Python<'py>, community_id: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, c.dissolve().await.map_err(err))
    }

    // ---- roles ----

    fn community_roles(&self, community_id: String) -> PyResult<Json> {
        self.bot.community(community_id).roles().map(|r| json_of(&r)).map_err(err)
    }

    #[pyo3(signature = (community_id, name, color=None, permissions=None, channel_id=None, shown=None, mentionable=None))]
    #[allow(clippy::too_many_arguments)]
    fn community_create_role<'py>(&self, py: Python<'py>, community_id: String, name: String, color: Option<u32>, permissions: Option<u64>, channel_id: Option<String>, shown: Option<bool>, mentionable: Option<bool>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        let spec = role_spec(Some(name), color, permissions, channel_id, shown, mentionable);
        fut!(py, c.create_role(spec).await.map(|r| r.id().to_string()).map_err(err))
    }

    fn community_reorder_roles<'py>(&self, py: Python<'py>, community_id: String, top_first: Vec<String>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, {
            let roles: Vec<_> = top_first.into_iter().map(|id| c.role(id)).collect();
            let refs: Vec<&_> = roles.iter().collect();
            c.reorder_roles(&refs).await.map_err(err)
        })
    }

    fn community_everyone_permissions(&self, community_id: String) -> PyResult<Option<u64>> {
        self.bot.community(community_id).everyone_permissions().map(|p| p.map(|p| p.0)).map_err(err)
    }

    fn community_set_everyone_permissions<'py>(&self, py: Python<'py>, community_id: String, permissions: u64) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, c.set_everyone_permissions(Permissions(permissions)).await.map_err(err))
    }

    fn role_info(&self, community_id: String, role_id: String) -> PyResult<Json> {
        self.bot.community(community_id).role(role_id).info().map(|r| json_of(&r)).map_err(err)
    }

    fn role_holders(&self, community_id: String, role_id: String) -> PyResult<Vec<String>> {
        self.bot.community(community_id).role(role_id).holders().map_err(err)
    }

    #[pyo3(signature = (community_id, role_id, name=None, color=None, permissions=None, channel_id=None, shown=None, mentionable=None))]
    #[allow(clippy::too_many_arguments)]
    fn role_edit<'py>(&self, py: Python<'py>, community_id: String, role_id: String, name: Option<String>, color: Option<u32>, permissions: Option<u64>, channel_id: Option<String>, shown: Option<bool>, mentionable: Option<bool>) -> PyResult<Bound<'py, PyAny>> {
        let r = self.bot.community(community_id).role(role_id);
        let spec = role_spec(name, color, permissions, channel_id, shown, mentionable);
        fut!(py, r.edit(spec).await.map_err(err))
    }

    fn role_delete<'py>(&self, py: Python<'py>, community_id: String, role_id: String) -> PyResult<Bound<'py, PyAny>> {
        let r = self.bot.community(community_id).role(role_id);
        fut!(py, r.delete().await.map_err(err))
    }

    // ---- categories ----

    fn community_categories(&self, community_id: String) -> PyResult<Json> {
        self.bot.community(community_id).categories().map(|v| json_of(&v)).map_err(err)
    }

    fn community_create_category<'py>(&self, py: Python<'py>, community_id: String, name: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, c.create_category(&name).await.map(|k| k.id().to_string()).map_err(err))
    }

    fn category_info(&self, community_id: String, category_id: String) -> PyResult<Json> {
        self.bot.community(community_id).category(category_id).info().map(|i| json_of(&i)).map_err(err)
    }

    fn category_channels(&self, community_id: String, category_id: String) -> PyResult<Json> {
        self.bot.community(community_id).category(category_id).channels().map(|i| json_of(&i)).map_err(err)
    }

    fn category_rename<'py>(&self, py: Python<'py>, community_id: String, category_id: String, name: String) -> PyResult<Bound<'py, PyAny>> {
        let k = self.bot.community(community_id).category(category_id);
        fut!(py, k.rename(&name).await.map_err(err))
    }

    fn category_move<'py>(&self, py: Python<'py>, community_id: String, category_id: String, index: usize) -> PyResult<Bound<'py, PyAny>> {
        let k = self.bot.community(community_id).category(category_id);
        fut!(py, k.move_to(index).await.map_err(err))
    }

    fn category_delete<'py>(&self, py: Python<'py>, community_id: String, category_id: String) -> PyResult<Bound<'py, PyAny>> {
        let k = self.bot.community(community_id).category(category_id);
        fut!(py, k.delete().await.map_err(err))
    }

    #[pyo3(signature = (community_id, category_id, target_kind, target_id, allow, deny))]
    #[allow(clippy::too_many_arguments)]
    fn category_set_overwrite<'py>(&self, py: Python<'py>, community_id: String, category_id: String, target_kind: String, target_id: Option<String>, allow: u64, deny: u64) -> PyResult<Bound<'py, PyAny>> {
        let ow = self.overwrite(&community_id, &target_kind, target_id, allow, deny)?;
        let k = self.bot.community(community_id).category(category_id);
        fut!(py, k.set_overwrite(ow).await.map_err(err))
    }

    // ---- moderation state, relays, images, recovery ----

    fn community_timeouts(&self, community_id: String) -> PyResult<Vec<(String, u64)>> {
        self.bot.community(community_id).timeouts().map_err(err)
    }

    fn community_nicknames(&self, community_id: String) -> PyResult<Vec<(String, String)>> {
        self.bot.community(community_id).nicknames().map_err(err)
    }

    fn community_audit_log<'py>(&self, py: Python<'py>, community_id: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, c.audit_log().await.map(|l| Json(audit_json(&l))).map_err(err))
    }

    fn community_relays(&self, community_id: String) -> PyResult<Vec<String>> {
        self.bot.community(community_id).relays().map_err(err)
    }

    fn community_check_relays<'py>(&self, py: Python<'py>, community_id: String, relays: Vec<String>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, c.check_relays(&relays).await.map(|r| json_of(&r)).map_err(err))
    }

    fn community_move_relays<'py>(&self, py: Python<'py>, community_id: String, relays: Vec<String>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, c.move_relays(&relays).await.map(|r| json_of(&r)).map_err(err))
    }

    fn community_voice_relays(&self, community_id: String) -> PyResult<Vec<String>> {
        self.bot.community(community_id).voice_relays().map_err(err)
    }

    fn community_set_voice_relays<'py>(&self, py: Python<'py>, community_id: String, relays: Vec<String>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, c.set_voice_relays(&relays).await.map_err(err))
    }

    fn community_icon<'py>(&self, py: Python<'py>, community_id: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, c.icon().await.map(|o| o.map(Bytes)).map_err(err))
    }

    fn community_banner<'py>(&self, py: Python<'py>, community_id: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, c.banner().await.map(|o| o.map(Bytes)).map_err(err))
    }

    #[pyo3(signature = (community_id, image=None))]
    fn community_set_icon<'py>(&self, py: Python<'py>, community_id: String, image: Option<&[u8]>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        let image = image.map(<[u8]>::to_vec);
        fut!(py, match image {
            Some(b) => c.set_icon(&b).await.map_err(err),
            None => c.remove_icon().await.map_err(err),
        })
    }

    #[pyo3(signature = (community_id, image=None))]
    fn community_set_banner<'py>(&self, py: Python<'py>, community_id: String, image: Option<&[u8]>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        let image = image.map(<[u8]>::to_vec);
        fut!(py, match image {
            Some(b) => c.set_banner(&b).await.map_err(err),
            None => c.remove_banner().await.map_err(err),
        })
    }

    fn community_refound<'py>(&self, py: Python<'py>, community_id: String, retain: Vec<String>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, {
            let refs: Vec<&str> = retain.iter().map(String::as_str).collect();
            c.refound(&refs).await.map_err(err)
        })
    }

    fn community_rescue_stranded<'py>(&self, py: Python<'py>, community_id: String, npubs: Vec<String>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, {
            let refs: Vec<&str> = npubs.iter().map(String::as_str).collect();
            c.rescue_stranded(&refs).await.map(Json).map_err(err)
        })
    }

    fn community_repair_roster<'py>(&self, py: Python<'py>, community_id: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, c.repair_roster().await.map(Json).map_err(err))
    }

    fn community_explain_epoch<'py>(&self, py: Python<'py>, community_id: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        fut!(py, c.explain_epoch().await.map(Json).map_err(err))
    }

    // ======================================================================================
    // Members
    // ======================================================================================

    fn member_kick<'py>(&self, py: Python<'py>, community_id: String, npub: String) -> PyResult<Bound<'py, PyAny>> {
        let m = self.bot.community(community_id).member(npub);
        fut!(py, m.kick().await.map_err(err))
    }

    fn member_ban<'py>(&self, py: Python<'py>, community_id: String, npub: String) -> PyResult<Bound<'py, PyAny>> {
        let m = self.bot.community(community_id).member(npub);
        fut!(py, m.ban().await.map_err(err))
    }

    fn member_unban<'py>(&self, py: Python<'py>, community_id: String, npub: String) -> PyResult<Bound<'py, PyAny>> {
        let m = self.bot.community(community_id).member(npub);
        fut!(py, m.unban().await.map_err(err))
    }

    fn member_is_banned(&self, community_id: String, npub: String) -> bool {
        self.bot.community(community_id).member(npub).is_banned()
    }

    fn member_grant_admin<'py>(&self, py: Python<'py>, community_id: String, npub: String) -> PyResult<Bound<'py, PyAny>> {
        let m = self.bot.community(community_id).member(npub);
        fut!(py, m.grant_admin().await.map_err(err))
    }

    fn member_revoke_admin<'py>(&self, py: Python<'py>, community_id: String, npub: String) -> PyResult<Bound<'py, PyAny>> {
        let m = self.bot.community(community_id).member(npub);
        fut!(py, m.revoke_admin().await.map_err(err))
    }

    fn member_is_owner(&self, community_id: String, npub: String) -> bool {
        self.bot.community(community_id).member(npub).is_owner()
    }

    fn member_is_admin(&self, community_id: String, npub: String) -> PyResult<bool> {
        self.bot.community(community_id).member(npub).try_is_admin().map_err(err)
    }

    fn member_can(&self, community_id: String, npub: String, permission: u64) -> PyResult<bool> {
        self.bot.community(community_id).member(npub).try_can(permission).map_err(err)
    }

    fn member_can_read(&self, community_id: String, npub: String, channel_id: String) -> bool {
        self.bot.community(community_id).member(npub).can_read(&channel_id)
    }

    fn member_permissions(&self, community_id: String, npub: String) -> PyResult<u64> {
        self.bot.community(community_id).member(npub).permissions().map(|p| p.0).map_err(err)
    }

    fn member_roles(&self, community_id: String, npub: String) -> PyResult<Json> {
        self.bot.community(community_id).member(npub).roles().map(|r| json_of(&r)).map_err(err)
    }

    fn member_set_roles<'py>(&self, py: Python<'py>, community_id: String, npub: String, role_ids: Vec<String>) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        let m = c.member(npub);
        fut!(py, {
            let roles: Vec<_> = role_ids.into_iter().map(|id| c.role(id)).collect();
            let refs: Vec<&_> = roles.iter().collect();
            m.set_roles(&refs).await.map_err(err)
        })
    }

    fn member_add_role<'py>(&self, py: Python<'py>, community_id: String, npub: String, role_id: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        let (m, r) = (c.member(npub), c.role(role_id));
        fut!(py, m.add_role(&r).await.map_err(err))
    }

    fn member_remove_role<'py>(&self, py: Python<'py>, community_id: String, npub: String, role_id: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.bot.community(community_id);
        let (m, r) = (c.member(npub), c.role(role_id));
        fut!(py, m.remove_role(&r).await.map_err(err))
    }

    fn member_timeout<'py>(&self, py: Python<'py>, community_id: String, npub: String, seconds: f64) -> PyResult<Bound<'py, PyAny>> {
        let m = self.bot.community(community_id).member(npub);
        fut!(py, m.timeout(Duration::from_secs_f64(seconds.max(0.0))).await.map_err(err))
    }

    fn member_remove_timeout<'py>(&self, py: Python<'py>, community_id: String, npub: String) -> PyResult<Bound<'py, PyAny>> {
        let m = self.bot.community(community_id).member(npub);
        fut!(py, m.remove_timeout().await.map_err(err))
    }

    fn member_timed_out_until(&self, community_id: String, npub: String) -> PyResult<Option<u64>> {
        self.bot.community(community_id).member(npub).timed_out_until().map_err(err)
    }

    fn member_nickname(&self, community_id: String, npub: String) -> Option<String> {
        self.bot.community(community_id).member(npub).nickname()
    }

    fn member_set_nickname<'py>(&self, py: Python<'py>, community_id: String, npub: String, nickname: String) -> PyResult<Bound<'py, PyAny>> {
        let m = self.bot.community(community_id).member(npub);
        fut!(py, m.set_nickname(&nickname).await.map_err(err))
    }

    // ======================================================================================
    // Mini Apps (WebXDC)
    // ======================================================================================

    /// Register a Mini App handler. Sessions arrive as `{"type": "xdc_session", "handler": id, …}`.
    #[cfg(feature = "xdc")]
    #[pyo3(signature = (app, join_when="opened".to_string(), idle_timeout=Some(180.0), quiet_timeout=Some(900.0), max_sessions=32, max_per_chat=4, by_hash=false))]
    #[allow(clippy::too_many_arguments)]
    fn register_xdc(&self, app: String, join_when: String, idle_timeout: Option<f64>, quiet_timeout: Option<f64>, max_sessions: usize, max_per_chat: usize, by_hash: bool) -> PyResult<u64> {
        use std::sync::atomic::Ordering;
        let id = self.next_xdc_handler.fetch_add(1, Ordering::Relaxed);
        let matcher = if by_hash { vector_sdk::XdcMatch::Hash(app) } else { vector_sdk::XdcMatch::from(app.as_str()) };
        let when = match join_when.as_str() {
            "opened" => vector_sdk::JoinWhen::Opened,
            "shared" => vector_sdk::JoinWhen::Shared,
            w => return Err(PyValueError::new_err(format!("join_when must be 'opened' or 'shared', not {w:?}"))),
        };
        let tx = self.tx.clone();
        self.bot
            .xdc(matcher)
            .join_when(when)
            .idle_timeout(idle_timeout.map(Duration::from_secs_f64))
            .quiet_timeout(quiet_timeout.map(Duration::from_secs_f64))
            .max_sessions(max_sessions)
            .max_per_chat(max_per_chat)
            .run(move |_bot, session| {
                let tx = tx.clone();
                async move {
                    let _ = tx.send(Inbound::XdcSession { handler: id, session });
                }
            });
        Ok(id)
    }

    /// The Mini App attached to a stored message, as `{chat_id, message_id, file_name, …}`.
    #[cfg(feature = "xdc")]
    fn message_xdc<'py>(&self, py: Python<'py>, message_id: String) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, Ok(bot.message(&message_id).await.and_then(|m| m.xdc()).map(|x| Json(crate::xdc::app_json(&x)))))
    }

    #[cfg(feature = "xdc")]
    fn xdc_manifest<'py>(&self, py: Python<'py>, message_id: String) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, {
            let x = bot.message(&message_id).await.and_then(|m| m.xdc()).ok_or_else(|| other("that message carries no Mini App"))?;
            x.manifest().await.map(|m| Json(crate::xdc::manifest_json(&m))).map_err(err)
        })
    }

    #[cfg(feature = "xdc")]
    fn xdc_join<'py>(&self, py: Python<'py>, message_id: String) -> PyResult<Bound<'py, PyAny>> {
        let bot = self.bot.clone();
        fut!(py, {
            let x = bot.message(&message_id).await.and_then(|m| m.xdc()).ok_or_else(|| other("that message carries no Mini App"))?;
            x.join().await.map(crate::xdc::NativeXdcSession::new).map_err(err)
        })
    }

    #[cfg(feature = "xdc")]
    fn channel_send_xdc<'py>(&self, py: Python<'py>, id: String, kind: Option<String>, path: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, kind.as_deref());
        fut!(py, c.send_xdc(path).await.map(|x| Json(crate::xdc::app_json(&x))).map_err(err))
    }

    // ======================================================================================
    // Voice
    // ======================================================================================

    #[cfg(feature = "voice")]
    fn channel_join_voice<'py>(&self, py: Python<'py>, id: String) -> PyResult<Bound<'py, PyAny>> {
        let c = self.ch(id, Some("community"));
        fut!(py, c.join_voice().await.map(crate::voice::NativeVoiceCall::new).map_err(err))
    }

    #[cfg(feature = "voice")]
    fn channel_voice_members(&self, id: String) -> Json {
        json_of(&self.ch(id, Some("community")).voice_members())
    }
}
