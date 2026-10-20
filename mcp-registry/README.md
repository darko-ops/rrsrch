# Listing RRSRCH in the MCP Registry

`server.json` describes the hosted server (https://rrsrch.com/mcp) for the official MCP Registry
(registry.modelcontextprotocol.io) under the `com.rrsrch/` namespace. Directories such as Glama read the registry.

The registry checks that we control rrsrch.com by fetching https://rrsrch.com/.well-known/mcp-registry-auth, which
holds the public half of an Ed25519 key. The private half lives only on the owner's machine, in an owner-only file
outside this repository; never commit it.

To publish (or publish a new version: bump `version` first):

```
brew install mcp-publisher
mcp-publisher login http --domain rrsrch.com \
  --private-key "$(openssl pkey -in ~/.config/rrsrch/mcp-registry-key.pem -noout -text | grep -A3 'priv:' | tail -n +2 | tr -d ' :\n')"
cd mcp-registry && mcp-publisher publish
```

`/.well-known/mcp/server-card.json` (in `rrsrch-react/public`) is the server card Smithery and others read when they
can't scan the server. It lists the tools as the server reported them; regenerate it when the tools change.
