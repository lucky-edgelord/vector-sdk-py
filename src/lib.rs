//! `vector._native`: PyO3 bindings for the Vector messenger Rust SDK (`vector_sdk`).
//!
//! This module is an implementation detail; use the `vector` Python package, which wraps it in
//! a discord.py-style API.

use pyo3::prelude::*;

mod bot;
mod convert;
#[cfg(feature = "voice")]
mod voice;
#[cfg(feature = "xdc")]
mod xdc;

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = m.py();
    m.add("__sdk_version__", "0.12.0")?;
    m.add_class::<bot::NativeBot>()?;

    m.add("VectorException", py.get_type::<convert::VectorException>())?;
    m.add("NotPermitted", py.get_type::<convert::NotPermitted>())?;
    m.add("NotFound", py.get_type::<convert::NotFound>())?;
    m.add("NotInitialized", py.get_type::<convert::NotInitialized>())?;
    m.add("NetworkError", py.get_type::<convert::NetworkError>())?;

    #[cfg(feature = "xdc")]
    {
        m.add_class::<xdc::NativeXdcSession>()?;
        m.add_function(wrap_pyfunction!(xdc::allow_outside_transport, m)?)?;
    }

    #[cfg(feature = "voice")]
    {
        m.add_class::<voice::NativeVoiceCall>()?;
        m.add_class::<voice::NativeSpeech>()?;
        m.add_class::<voice::NativeUtterances>()?;
        m.add_function(wrap_pyfunction!(voice::tone, m)?)?;
        m.add_function(wrap_pyfunction!(voice::level, m)?)?;
        m.add_function(wrap_pyfunction!(voice::decode_with_ffmpeg, m)?)?;
        m.add("SAMPLE_RATE", voice::SAMPLE_RATE)?;
        m.add("FRAME", voice::FRAME)?;
        #[cfg(feature = "whisper")]
        m.add_class::<voice::NativeTranscriber>()?;
    }
    Ok(())
}
