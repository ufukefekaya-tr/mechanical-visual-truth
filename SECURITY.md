# Security

MVT reads CAD files and writes project-local artifacts. Treat native geometry
parsers as parsers of untrusted input. The MCP server provides a local path
boundary, serialized worker timeouts and resource limits; it is not an OS
sandbox. For hostile inputs, isolate its OS user/container and restrict mounts.

Do not put credentials, private conversations or customer source models in an
issue. Report a vulnerability privately through GitHub's security reporting
facility for this repository when enabled; otherwise contact the maintainer
through the GitHub profile and ask for a private channel before disclosing it.
