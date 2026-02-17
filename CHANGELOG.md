# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- PSR-INSERT-FLAG -->
## [1.0.0] - 2026-02-17

### Added

- First stable release ([`5af975e`](https://github.com/seanbrar/pollux/commit/5af975e232c53ce3b10989e49a869fc0fc7d49ed))
- Accept Windows path prefixes in runner ([`c54dec5`](https://github.com/seanbrar/pollux/commit/c54dec5ae9b91d33a223eb220bd09721df53d97b))
- Add demo-data seeding + module runner; migrate recipes to --input; add provider uploads ([`eb6ed22`](https://github.com/seanbrar/pollux/commit/eb6ed2224a4a2aa6559d039a90e5062697067276))
- Add stdlib logging for pipeline observability ([`d231d16`](https://github.com/seanbrar/pollux/commit/d231d16ecd797558738c274dc2ece0f2b9617150))
- Structured error hierarchy with retry metadata ([`76c15da`](https://github.com/seanbrar/pollux/commit/76c15da48187380ee5ba75e0d3cf2d4891e77a6a))
- Add bounded retries ([`5f3111d`](https://github.com/seanbrar/pollux/commit/5f3111d17f0b6889a252a01ac0573814da3c5880))
- Support Python 3.10+ ([`acbe7e7`](https://github.com/seanbrar/pollux/commit/acbe7e7b1d9aec988edcef9fd22a7b5222816199))
- Introduce v1 execution architecture and retire legacy runtime ([`95c22d1`](https://github.com/seanbrar/pollux/commit/95c22d1dd2707d6f55584d0e50333d54ce6e1567))
- Actionable error hints and PolluxError rebranding ([`fba14a5`](https://github.com/seanbrar/pollux/commit/fba14a5e934e887aa155b52c7b2be4a0f5e55711))
- Branded homepage, unified palette, and layout refinements ([`02602e8`](https://github.com/seanbrar/pollux/commit/02602e87cff69adafb0006a96c86a7bf04489784))

### Fixed

- Normalize usage keys to provider-agnostic names ([`3f14517`](https://github.com/seanbrar/pollux/commit/3f1451731ea835d98439f25bddf270290b94ed95))
- Add gate job for branch protection required check ([`d089236`](https://github.com/seanbrar/pollux/commit/d089236b392e96e7d3687ecd32eb02f5b393f87e))
- Restrict docs deploy to main branch only ([`a57d0ff`](https://github.com/seanbrar/pollux/commit/a57d0ff947486ec92ba2b039fd24a82743a48e8a))
- Refresh uv lock after package rename ([`b3a1533`](https://github.com/seanbrar/pollux/commit/b3a1533dc335b28a22b2e61c80f18c1998b42fc0))
- Rename PyPI distribution to pollux-ai ([`1fb860c`](https://github.com/seanbrar/pollux/commit/1fb860c9eb526576d7073f73faf13b6fb2f598a6))
- Remove redundant config replacement in cache-warming recipe ([`da5068d`](https://github.com/seanbrar/pollux/commit/da5068dd4976450ec30f8b76280a80b96b050402))
- Harden execution concurrency and tighten boundary tests ([`8903a33`](https://github.com/seanbrar/pollux/commit/8903a33502cc4b37a405269c732784dab7ddedbf))
- Build dists on runner for semantic-release ([`95670e9`](https://github.com/seanbrar/pollux/commit/95670e9c3daf3c18cab166afe6184d1af18a2dd3))
- Bind trusted publisher to pypi environment ([`670a146`](https://github.com/seanbrar/pollux/commit/670a1460e4cba2eaa719400732328addf2412086))
- Make force input optional string ([`e4cfa7b`](https://github.com/seanbrar/pollux/commit/e4cfa7b2ce09382abb95f58aa57bd42e355c3660))
- Enable OIDC prerelease flow on release branches ([`c0b553c`](https://github.com/seanbrar/pollux/commit/c0b553c4d88c51a1b2b1da118141cedca809611c))

### Changed

- V1.0 documentation pass — accuracy, structure, and API doc-comments ([`39b285f`](https://github.com/seanbrar/pollux/commit/39b285f894345300360691862200a798fe8c7ebd))
- Refine roadmap and issue templates ([`ea61e9a`](https://github.com/seanbrar/pollux/commit/ea61e9af36c453ac7bdd753158f5b85d45d7c5f9))
- Refresh docs for v1.0 ([`25fc61e`](https://github.com/seanbrar/pollux/commit/25fc61e942ed241ec475efae649a8a2650c23986))
- Complete documentation overhaul for v1.0 ([`c26cb8c`](https://github.com/seanbrar/pollux/commit/c26cb8c47f1a3dd8955b8088a442948d902a52e4))
- Add comprehensive user onboarding for v0.9 release ([`f8dfebc`](https://github.com/seanbrar/pollux/commit/f8dfebc511a56e20a1e3ce59b4b7fc5c1cf099a9))
- Reduce import overhead and config churn ([`b802736`](https://github.com/seanbrar/pollux/commit/b8027363940ca76674119db1e545481054b69fda))
- Restructure navigation, add guides, enable strict CI ([`9e103c5`](https://github.com/seanbrar/pollux/commit/9e103c51a24d16465221d3e61358e7d4cc595a07))

## [0.9.0] - 2025-09-01

### Added

- Complete command pipeline system with production-ready multimodal batch processing ([`fe86af7`](https://github.com/seanbrar/pollux/commit/fe86af7ef3359d4a3a2d69ad3588f76c407648cc))
- Complete GSoC 2025 with production-ready extensions and cookbook ([`3518c56`](https://github.com/seanbrar/pollux/commit/3518c566d0259d1b8a1486cbd9ea6fded68ac743))
- Add efficiency benchmarking with token-economics optimization ([`32570b7`](https://github.com/seanbrar/pollux/commit/32570b70237d591a73c0c34e87f070eaa4de08ed))

### Fixed

- Resolve test environment conflict preventing CI green status ([`45b7096`](https://github.com/seanbrar/pollux/commit/45b7096cbfb78799ad1111aa691255223f127f4c))

### Changed

- Introduce `mkdocs` tooling and formalize architectural documentation using Diátaxis framework ([`80b70ae`](https://github.com/seanbrar/pollux/commit/80b70aee96cef1841555250e9ad43076b34bd026))

## [0.8.0] - 2025-08-04

### Added

- Complete automated release infrastructure with semantic versioning ([`a17f6b5`](https://github.com/seanbrar/pollux/commit/a17f6b50f3b9a1c948110db14bbfe386ec2d43b8))
- Implement Jinja2 template for changelog ([`7a250d9`](https://github.com/seanbrar/pollux/commit/7a250d9e29647823ddd4dab258a02964477feeb5))

### Fixed

- Standardize usage metadata key in API responses ([`dd7b3e8`](https://github.com/seanbrar/pollux/commit/dd7b3e88e1797242dc6eb272dbcc460d4351957f))

### Changed

- Enhance main project README ([`586cec9`](https://github.com/seanbrar/pollux/commit/586cec9ba5fd72fa862e63487dbe35841093173a))
- Add CODE_OF_CONDUCT and PR template ([`5f3aef9`](https://github.com/seanbrar/pollux/commit/5f3aef96e0753b14bc4d8d79a20e180b6b2d8383))

## [0.7.0] - 2025-07-23

### Added

- Initial commit with basic client and batch logic ([`c88a2df`](https://github.com/seanbrar/pollux/commit/c88a2dfaff1fadf8c8861c136a85156411dad929))
- Implement batch processing framework ([`44cc0ad`](https://github.com/seanbrar/pollux/commit/44cc0ad0398bdf5ab9a447bff04329bb8a81aa1e))
- Implement context caching with lifecycle management ([`251b7c9`](https://github.com/seanbrar/pollux/commit/251b7c9f6e59eb533a555db724df2c20d9802de7))
- Implement conversation memory with cross-source synthesis ([`172c9c3`](https://github.com/seanbrar/pollux/commit/172c9c3a904267dad9eb93ceb3f26eb293396b26))
- Add multimodal architecture for multi-source analysis ([`df87fa5`](https://github.com/seanbrar/pollux/commit/df87fa52f3a9eb9b78b350be40de20614ae8037d))
- Establish foundation and basic API client ([`19642c8`](https://github.com/seanbrar/pollux/commit/19642c838f6df1ee275958166bbf48d8ae97d0ab))
- Add performance monitoring and architectural modernization ([`498e846`](https://github.com/seanbrar/pollux/commit/498e846356892f230d8ba210e2c3d249129abdac))

<!-- PSR-LINKS-START -->
[1.0.0]: https://github.com/seanbrar/pollux/compare/v0.9.0...v1.0.0
[0.9.0]: https://github.com/seanbrar/pollux/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/seanbrar/pollux/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/seanbrar/pollux/releases/tag/v0.7.0
