# Security

Please report security-sensitive issues privately rather than opening a public issue when disclosure could create avoidable risk.

This project is a guardrail and provenance toolkit, not a secure sandbox. Code that can import CUDA-Q directly can bypass the guard unless the surrounding deployment restricts that path. See [docs/security-model.md](docs/security-model.md) for the intended boundary and limitations.
