# Third-party notices

vector-sdk-py is released under the MIT license (see `LICENSE`). Its compiled extension links these projects, which
keep their own licenses and copyright notices.

## vector_sdk

The Rust SDK for the Vector messenger, from <https://github.com/VectorPrivacy/Vector>
(<https://crates.io/crates/vector_sdk>), version 0.12.0, licensed under the MIT license. The copyright notice and
license text are those published in the upstream repository and crate; they apply to `vector_sdk` and are
reproduced there. This project only depends on the crate (it does not copy its source into this repository).

## Other Rust dependencies

The wheels also contain PyO3, pyo3-async-runtimes, tokio and the transitive dependencies of `vector_sdk`, each under
its own permissive license (MIT and/or Apache-2.0 in the common case). Generate the complete, exact list for a
release with `cargo about` or `cargo license` against `Cargo.lock`, and ship it with the wheels.

## Compatibility with other projects

discord.py (MIT), aoi.js (Apache-2.0), Bot Designer for Discord (BDFD, BDScript 2) and Discord are referenced only
to describe API and syntax compatibility. No source code from those projects is included here, and this project is
not affiliated with or endorsed by any of them.
