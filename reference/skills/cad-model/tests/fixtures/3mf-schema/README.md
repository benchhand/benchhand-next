# 3MF schemas for the part.3mf tests

These XSDs validate the XML parts of a written `part.3mf`. They are copied from the 3MF Consortium under the
BSD 2-Clause licences kept beside them. `3mf-core.xsd` has two edits, listed below; the rest is unchanged.

| File | Source | Licence |
|---|---|---|
| `3mf-core.xsd` | Appendix B.1.1 of the [3MF Core Specification 1.4.0](https://github.com/3MFConsortium/spec_core/tree/1.4.0) (commit 997b385). The `xml.xsd` import points at the local copy instead of w3.org, and `maxOccurs="2147483647"` reads `unbounded`, which libxml2 accepts. | `LICENSE.spec_core` |
| `opc-contentTypes.xsd`, `opc-relationships.xsd` | `Consolidated_Schema/Schema` of [3MFConsortium/test_suites](https://github.com/3MFConsortium/test_suites) (commit f483d3b) | `LICENSE.test_suites` |
| `xml.xsd` | The W3C XML namespace schema, https://www.w3.org/2001/xml.xsd, fetched 2026-11-18, unmodified (sha256 `61960fb3131e38022caad5360e2f33a3382578ab3c80cd58bd74320ede61b20c`). The W3C Document License allows redistribution without modification. | `LICENSES/LicenseRef-W3C-Document-2023.txt` |

The consolidated `qli_3MF.xsd` of test_suites is not used. It makes the Production extension's `p:UUID`
attribute required on every `object` and `item`, so it rejects a package that, like ours, has no extension.
The Core specification schema is the authoritative one for Core 1.4.0.
