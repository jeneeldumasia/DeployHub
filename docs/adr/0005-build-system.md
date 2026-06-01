# ADR 0005: Build System

**Status:** ACCEPTED
**Context:** We need to convert source code to OCI container images automatically.
**Decision:** We will use Cloud Native Buildpacks as the primary build engine. A Dockerfile build will be used exclusively as a fallback when no buildpack detects the project. 
**Consequences:** 
- Zero-configuration builds for supported runtimes (Node.js, Python, Go, Java, Rust, .NET, PHP).
- Prevents maintenance overhead of custom framework detection logic.
**Conflict Resolution Policy:** Custom detection scripts will be rejected. Fallback logic must only execute if buildpacks return zero matches.
