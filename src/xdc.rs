//! Mini App (WebXDC) sessions.

use std::sync::Arc;
use std::time::Duration;

use pyo3::prelude::*;
use serde_json::{json, Value};
use tokio::sync::Mutex;
use vector_sdk::{Manifest, Xdc, XdcEvent, XdcPeer, XdcSender, XdcSession};

use crate::convert::{err, hex, other, value_to_py, Bytes, Json};

macro_rules! fut {
    ($py:ident, $($body:tt)*) => {
        pyo3_async_runtimes::tokio::future_into_py($py, async move { $($body)* })
    };
}

pub fn app_json(x: &Xdc) -> Value {
    json!({
        "chat_id": x.chat_id(),
        "message_id": x.message_id(),
        "file_name": x.file_name(),
        "file_hash": x.file_hash(),
        "topic": x.topic(),
        "attachment": serde_json::to_value(x.attachment()).unwrap_or(Value::Null),
    })
}

pub fn manifest_json(m: &Manifest) -> Value {
    json!({
        "name": m.name, "id": m.id, "description": m.description, "icon": m.icon,
        "version": m.version, "source_code_url": m.source_code_url,
    })
}

fn peer_json(p: &XdcPeer) -> Value {
    json!({"node": hex(&p.node), "npub": p.npub})
}

/// A live session with everyone who has a Mini App open.
#[pyclass(module = "vector._native")]
pub struct NativeXdcSession {
    inner: Arc<Mutex<Option<XdcSession>>>,
    sender: XdcSender,
    app: Value,
    self_addr: String,
}

impl NativeXdcSession {
    pub fn new(s: XdcSession) -> Self {
        NativeXdcSession { sender: s.sender(), app: app_json(s.app()), self_addr: s.self_addr().to_string(), inner: Arc::new(Mutex::new(Some(s))) }
    }
}

#[pymethods]
impl NativeXdcSession {
    #[getter]
    fn app<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        value_to_py(py, &self.app)
    }

    #[getter]
    fn self_addr(&self) -> String {
        self.self_addr.clone()
    }

    /// Next event as a dict (`data` / `peer_join` / `peer_leave` / `lagged`), or `None` when it ends.
    fn next<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner.clone();
        fut!(py, {
            let mut guard = inner.lock().await;
            let Some(s) = guard.as_mut() else { return Ok(None) };
            Ok(s.next().await.map(|ev| match ev {
                XdcEvent::Data(f) => XdcItem::Data {
                    payload: f.payload.clone(),
                    from: peer_json(&f.from),
                    direct: f.direct,
                    verified: f.verified_sender().map(str::to_string),
                },
                XdcEvent::PeerJoined(p) => XdcItem::Plain(json!({"type": "peer_join", "peer": peer_json(&p)})),
                XdcEvent::PeerLeft(p) => XdcItem::Plain(json!({"type": "peer_leave", "peer": peer_json(&p)})),
                XdcEvent::Lagged => XdcItem::Plain(json!({"type": "lagged"})),
                #[allow(unreachable_patterns)]
                _ => XdcItem::Plain(json!({"type": "unknown"})),
            }))
        })
    }

    /// Send raw bytes to everyone in the session. Safe to call while another task awaits `next()`.
    fn send<'py>(&self, py: Python<'py>, data: &[u8]) -> PyResult<Bound<'py, PyAny>> {
        let s = self.sender.clone();
        let data = data.to_vec();
        fut!(py, s.send(data).await.map_err(err))
    }

    fn send_text<'py>(&self, py: Python<'py>, text: String) -> PyResult<Bound<'py, PyAny>> {
        let s = self.sender.clone();
        fut!(py, s.send_text(&text).await.map_err(err))
    }

    /// Send a JSON document (pass it already serialized: `json.dumps(obj)`).
    fn send_json<'py>(&self, py: Python<'py>, json_text: String) -> PyResult<Bound<'py, PyAny>> {
        let s = self.sender.clone();
        let v: Value = serde_json::from_str(&json_text).map_err(|e| other(e.to_string()))?;
        fut!(py, s.send_json(&v).await.map_err(err))
    }

    fn peers<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner.clone();
        fut!(py, {
            let g = inner.lock().await;
            Ok(Json(Value::Array(g.as_ref().map(|s| s.peers().iter().map(peer_json).collect()).unwrap_or_default())))
        })
    }

    #[pyo3(signature = (seconds=None))]
    fn set_idle_timeout<'py>(&self, py: Python<'py>, seconds: Option<f64>) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner.clone();
        fut!(py, {
            if let Some(s) = inner.lock().await.as_mut() {
                s.set_idle_timeout(seconds.map(Duration::from_secs_f64));
            }
            Ok(())
        })
    }

    #[pyo3(signature = (seconds=None))]
    fn set_quiet_timeout<'py>(&self, py: Python<'py>, seconds: Option<f64>) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner.clone();
        fut!(py, {
            if let Some(s) = inner.lock().await.as_mut() {
                s.set_quiet_timeout(seconds.map(Duration::from_secs_f64));
            }
            Ok(())
        })
    }

    fn leave<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let inner = self.inner.clone();
        fut!(py, {
            if let Some(s) = inner.lock().await.take() {
                s.leave().await;
            }
            Ok(())
        })
    }
}

enum XdcItem {
    Data { payload: Vec<u8>, from: Value, direct: bool, verified: Option<String> },
    Plain(Value),
}

impl<'py> IntoPyObject<'py> for XdcItem {
    type Target = PyAny;
    type Output = Bound<'py, PyAny>;
    type Error = PyErr;

    fn into_pyobject(self, py: Python<'py>) -> Result<Self::Output, Self::Error> {
        match self {
            XdcItem::Plain(v) => value_to_py(py, &v),
            XdcItem::Data { payload, from, direct, verified } => {
                let d = value_to_py(py, &json!({"type": "data", "from": from, "direct": direct, "verified_sender": verified}))?;
                d.set_item("payload", Bytes(payload).into_pyobject(py)?)?;
                Ok(d)
            }
        }
    }
}

/// Let sessions join even when the bot runs over Tor or I2P (peers can see the bot's IP).
#[pyfunction]
pub fn allow_outside_transport(on: bool) {
    vector_sdk::xdc::allow_outside_transport(on);
}
