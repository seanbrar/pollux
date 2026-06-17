# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!-- PSR-INSERT-FLAG -->
## [2.0.0-rc.1] - 2026-06-17

### Added

- Add Session runtime and provider readiness probes ([`91b51c9`](https://github.com/seanbrar/pollux/commit/91b51c907a12c4ede634b2cbef319ce79b1f5805))
- Add stream() for incremental interaction output ([`a197a89`](https://github.com/seanbrar/pollux/commit/a197a893089c56a8dafae06f2474ac6c78ebc026))
- Move defer()/collect_deferred() to the v2 model ([`12fc06f`](https://github.com/seanbrar/pollux/commit/12fc06f8c18738e46fea641a5c4d78101291fed8))
- Flip run()/run_many() to the v2 Output model ([`313feab`](https://github.com/seanbrar/pollux/commit/313feabbcaecf2e01968700294020863495da493))
- Add interact() v2 frontdoor ([`9ea3536`](https://github.com/seanbrar/pollux/commit/9ea353684bdc7f2713adab118624806dd4ef661e))
- Migrate the project recipes to the v2 API ([`67eebe4`](https://github.com/seanbrar/pollux/commit/67eebe4341ea036bcabac5a5f94e5e4174cc0378))
- Add error taxonomy and OpenAI message interop ([`a63b666`](https://github.com/seanbrar/pollux/commit/a63b666bf720ab0536a9e1a1cb19b8364a93c30b))
- Harden the local provider for multimodal agent loops ([`23f891b`](https://github.com/seanbrar/pollux/commit/23f891b950bb079fc2866f8d465ffc6500bf605f))
- Introduce ToolCall.arguments_dict and ToolResult.from_value ([`91f7787`](https://github.com/seanbrar/pollux/commit/91f7787cddc77775b64f7452f5eea3cd196b171c))
- Enforce continuation provider compatibility at runtime ([`fabbe41`](https://github.com/seanbrar/pollux/commit/fabbe414fdc647ca25ef370a22442de3b4926b5b))
- Stream from the OpenAI and Gemini providers ([`5bf9b9d`](https://github.com/seanbrar/pollux/commit/5bf9b9d2aebe1a565f0f1e4298beae14496b38a9))
- Stream from the Anthropic and OpenRouter providers ([`77f74b8`](https://github.com/seanbrar/pollux/commit/77f74b82b9d32b551bbfd719cec6005a9d8d63fd))
- Add tool calling to the local provider ([`de1473f`](https://github.com/seanbrar/pollux/commit/de1473f90ed6ea22c63618d598ba1cffd15deeaf))
- Remove the remaining public v1 surface ([`9c9cca6`](https://github.com/seanbrar/pollux/commit/9c9cca62a11b47e9f958f9184b027c4d2d3178a9))
- Flip the provider boundary to v2 primitives ([`65ff9af`](https://github.com/seanbrar/pollux/commit/65ff9afe3a72538cb0f6383c4ccce4e2f86b7207))
- Wire persistent caching into the v2 path ([`fcc9a4b`](https://github.com/seanbrar/pollux/commit/fcc9a4b366a4b25fb40304e285cae6f20aeeb968))
- Add v2 capability resolution and Config declarations ([`6eb1ca6`](https://github.com/seanbrar/pollux/commit/6eb1ca64b9df54fc170630998fd6ec30de1388af))
- Add v2 provider boundary and execution path ([`2bdb6ee`](https://github.com/seanbrar/pollux/commit/2bdb6ee552ddb162258173f4a01b8113eb0a439f))
- Add v2 interaction model types ([`b8c4e5b`](https://github.com/seanbrar/pollux/commit/b8c4e5bf35f6f488f2006db547894f351214467c))

### Changed

- Refresh the README for the v2 API ([`804469b`](https://github.com/seanbrar/pollux/commit/804469bab73ea300accf4826983f2344ceb8df12))
- Refresh the v2 migration guide for shipped behavior ([`58be4d3`](https://github.com/seanbrar/pollux/commit/58be4d33b5fb266b1990ff1f3d3b2ba6f23db44c))
- Align documentation with v2 API structure and terms ([`7197eff`](https://github.com/seanbrar/pollux/commit/7197effd0a21177bb2c0673c17379a4c53a4a5d9))

## [1.8.0] - 2026-06-13

### Added

- Stamp continuation state with schema version and provider ([`68fd568`](https://github.com/seanbrar/pollux/commit/68fd5684b588c435305256fa746a927f3daafedd))
- Pre-flight reject extended thinking on Claude 3 models ([`159d880`](https://github.com/seanbrar/pollux/commit/159d8801e371f4a18483c758c028a0d4c1fd68b1))
- Add v1 audit escape hatch ([`4984299`](https://github.com/seanbrar/pollux/commit/49842997a4a2f5c4f9c9d944d7e2b35c3625bb88))

### Changed

- Make recipes runnable and align source-pattern terminology ([`e80e785`](https://github.com/seanbrar/pollux/commit/e80e7856148a1d9a26db9e88c4da0755c63fde9e))
- Mark v2-removed entry points and add 2.0 migration stub ([`883ee51`](https://github.com/seanbrar/pollux/commit/883ee51485bc8881bfa275db533f8870dc894437))
- Streamline agent guidelines in AGENTS.md ([`8590344`](https://github.com/seanbrar/pollux/commit/859034465988b859a07b5c4f73a3f1244b00593d))
- Refine migration cleanup notes ([`0d9afc8`](https://github.com/seanbrar/pollux/commit/0d9afc8f94a9c50d9ecb85c2228daefa3dabf34a))

## [1.7.0] - 2026-04-22

### Added

- Deprecate Options.delivery_mode ahead of v1.8.0 ([`26e2157`](https://github.com/seanbrar/pollux/commit/26e2157f7d3bfa6c11d22bd19eb2a956bf58a5b9))
- Surface cached_tokens in result usage across all providers ([`1b94d3f`](https://github.com/seanbrar/pollux/commit/1b94d3f108643acc30801b2a6e6bf2d613de0f5a))
- Add reasoning budget tokens ([`1ab9df9`](https://github.com/seanbrar/pollux/commit/1ab9df95fb5d52db6ea040c79d468e4170abee3c))
- Add self-hosted text provider ([`009fd70`](https://github.com/seanbrar/pollux/commit/009fd70b3e2752b006e8195fe286a314c16cf443))

## [1.6.0] - 2026-03-21

### Added

- Add Gemini video metadata controls ([`f72dc37`](https://github.com/seanbrar/pollux/commit/f72dc3740c773910afc250deefd6b1ccca1a883a))

## [1.5.0] - 2026-03-17

### Added

- Add deferred delivery backends and lifecycle docs ([`384e189`](https://github.com/seanbrar/pollux/commit/384e18903cc98c6d827804c40b6b2c9bc4b7c7d2))
- Add deferred delivery public API ([`52bc1a8`](https://github.com/seanbrar/pollux/commit/52bc1a8f6d78d9652567b4e03fd0b1e6d6aa302b))
- Add deferred delivery backend ([`894d690`](https://github.com/seanbrar/pollux/commit/894d690e638fd8e513b146debd5ea87892d4831a))

### Changed

- Refresh README and roadmap for v1.5 ([`5acfeb4`](https://github.com/seanbrar/pollux/commit/5acfeb44517cbae8ef2a590a068f59ff7856a75f))

## [1.4.0] - 2026-03-09

### Added

- Add project recipes and starter data packs ([`22c3401`](https://github.com/seanbrar/pollux/commit/22c3401e3672daa59268293f3a68f19a83181a7b))
- Add projects tier and streamline README ([`d8d3668`](https://github.com/seanbrar/pollux/commit/d8d3668f7fadbaa384157111839a125d7f9ebdb6))
- Add reasoning controls and refine provider reasoning docs ([`98788e5`](https://github.com/seanbrar/pollux/commit/98788e54637ed1a43e04de7e1e92708abec59a1c))
- Add tools and structured outputs ([`7170a2b`](https://github.com/seanbrar/pollux/commit/7170a2b24a14dda5f1755447bf630dd8a892d722))
- Add OpenRouter support for image and PDF inputs ([`840699c`](https://github.com/seanbrar/pollux/commit/840699cfb19a551dfb657ecd26fe32a3fed872c0))
- Validate model capabilities from OpenRouter metadata ([`28ba2d4`](https://github.com/seanbrar/pollux/commit/28ba2d480e7630619a0560f8e1fba8e1e334259f))
- Add OpenRouter provider for text generation ([`725bc0e`](https://github.com/seanbrar/pollux/commit/725bc0e5a5e48e2ba56778fadd749ddd8a3fe1d8))

### Fixed

- Remove pack fallback when source_root is explicitly provided ([`8607de1`](https://github.com/seanbrar/pollux/commit/8607de10d4efb4e80829dd3b7d7375dbedca9c23))
- Configure explicit provider timeout to prevent truncation ([`7deaf82`](https://github.com/seanbrar/pollux/commit/7deaf82bd00a70c7760068d8e1ccd658a0ef4e01))
- Anthropic model-specific max_tokens behavior ([`daa80fa`](https://github.com/seanbrar/pollux/commit/daa80fa39800c30287ebe9f758634d57e157cdb8))

### Changed

- Improve vocabulary, caching docs, and README style ([`3b17574`](https://github.com/seanbrar/pollux/commit/3b17574c9ae9a5a9988c3d5f0cbab3ed21be4fed))

## [1.3.0] - 2026-03-06

### Added

- Add Anthropic implicit caching support ([`9869d96`](https://github.com/seanbrar/pollux/commit/9869d96f881369850281bf7b81128edb37a5da85))
- Implement explicit create_cache API ([`86d2039`](https://github.com/seanbrar/pollux/commit/86d2039756eab13357a0548b8fd62b0713704001))
- Update v1.3 integration and documentation ([`867783a`](https://github.com/seanbrar/pollux/commit/867783afd834c33547b7c46a5d6eba4b3e6b2fdf))
- Add Anthropic provider ([`667c4fc`](https://github.com/seanbrar/pollux/commit/667c4fc7b0b74e7a13695f30a29cf0d3771ea42a))
- Add Anthropic reasoning levels and thinking replay ([`a947450`](https://github.com/seanbrar/pollux/commit/a947450e541aaa60889d45db83843c4d0a7acfbb))

### Fixed

- Harden Anthropic provider and decompose provider generate() methods ([`027d5ea`](https://github.com/seanbrar/pollux/commit/027d5ea85160baa15c324716736d6bef758546cb))

## [1.2.2] - 2026-02-28

### Fixed

- Defer dotenv loading to Config initialization ([`a851b24`](https://github.com/seanbrar/pollux/commit/a851b249ac767d686362e255d969734347f4202b))

## [1.2.1] - 2026-02-28

### Fixed

- Normalize tool parameter schemas per-provider ([`8eb2c94`](https://github.com/seanbrar/pollux/commit/8eb2c94241feb55fd73c6976913f08e3d8d12608))
- Populate finish_reasons from provider responses ([`6d09119`](https://github.com/seanbrar/pollux/commit/6d0911900b9ba2bbb0674e8b53719eef251d1feb))
- Populate conversation state for tool-call responses without history ([`64247d9`](https://github.com/seanbrar/pollux/commit/64247d9c89568d3c0a5433690912ae552f35553f))

### Changed

- Fix stale references and document post-v1.2.0 behavior ([`b42a7db`](https://github.com/seanbrar/pollux/commit/b42a7db655098ad0545bca3a6177425266038e25))

## [1.2.0] - 2026-02-26

### Added

- Introduce continue_tool and fix continuation turn order mechanics ([`f1bd41c`](https://github.com/seanbrar/pollux/commit/f1bd41cc9ff10d67373ef9a1c418998f2ab715b3))
- Add reasoning/thinking support ([`a25a5f2`](https://github.com/seanbrar/pollux/commit/a25a5f291841ffc6af01b16a0b082065945c049c))
- Add Gemini conversation support and tool message pass-through (#118) ([`a32e32a`](https://github.com/seanbrar/pollux/commit/a32e32a6793562ce1c4309e2593e9f3db73ffb0b))
- Add tool-call transparency in conversation history ([`10852e1`](https://github.com/seanbrar/pollux/commit/10852e18a817304bdf39fbca7ac984cce2211c27))
- Add tool calling, generation params, and Source.from_json() ([`5b43d00`](https://github.com/seanbrar/pollux/commit/5b43d0041cbcacfaa21d55b9c8e3fd0981760604))

### Changed

- Restructure documentation around domain concepts ([`453feef`](https://github.com/seanbrar/pollux/commit/453feef4ef28e5660b91608b34e3ac00682eadab))

## [1.1.0] - 2026-02-20

### Added

- Add system_instruction and conversation continuity ([`3e5a683`](https://github.com/seanbrar/pollux/commit/3e5a6835a34c2144d65c80837744a0e89afcccb2))

### Changed

- Add AGENTS.md and CLAUDE.md for AI agent guidance ([`e49ba82`](https://github.com/seanbrar/pollux/commit/e49ba82fc35c1118699807a4b8e8d39b368b5a04))

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
[2.0.0-rc.1]: https://github.com/seanbrar/pollux/compare/v1.8.0...v2.0.0-rc.1
[1.8.0]: https://github.com/seanbrar/pollux/compare/v1.7.0...v1.8.0
[1.7.0]: https://github.com/seanbrar/pollux/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/seanbrar/pollux/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/seanbrar/pollux/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/seanbrar/pollux/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/seanbrar/pollux/compare/v1.2.2...v1.3.0
[1.2.2]: https://github.com/seanbrar/pollux/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/seanbrar/pollux/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/seanbrar/pollux/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/seanbrar/pollux/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/seanbrar/pollux/compare/v0.9.0...v1.0.0
[0.9.0]: https://github.com/seanbrar/pollux/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/seanbrar/pollux/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/seanbrar/pollux/releases/tag/v0.7.0
