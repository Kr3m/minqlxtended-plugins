# Discord QL Mover mapping sources

By default, `discord_ql_mover` reads Steam-to-Discord mappings from Fragdex. Create a Fragdex API key for this plugin and allow the game server's egress IP where practical. The key needs the normal read access (which Fragdex grants to API keys) and **Read Discord bot token** if QL Mover should also fetch its Discord bot token. Configure:

```text
set qlx_fragdex_api_url "https://fragdex.kr3m.one/api/v1"
set qlx_fragdex_api_key "<Fragdex API key>"
set qlx_dmoverUseFragdexMappings "1"
set qlx_dmoverUseRedisMappingFallback "0"
set qlx_dmoverUseCvarDiscordBotToken "0"
set qlx_fragdex_token_refresh_interval "3600"
```

`qlx_fragdex_api_url` and `qlx_fragdex_api_key` configure the API. Moves use Fragdex's batch `POST /players/lookup` endpoint (up to 100 Steam IDs per request); `!whois` uses `GET /players/{steam_id}` and `GET /discord/{discord_id}`. Requests use `Authorization: Bearer <key>` and run in background threads. An unmapped or unknown player, an ambiguous reverse lookup, or an API error is logged and skipped; Redis is not consulted unless its fallback is enabled. Fragdex API keys are rate-limited (120 requests/minute by default); `401`, `403`, and `429` responses are logged, and `429`'s `Retry-After` is included in the warning.

## Optional legacy modes

| Cvar | Default | Behavior |
|---|---:|---|
| `qlx_dmoverUseFragdexMappings` | `1` | Use Fragdex as the mapping source. Set to `0` to switch back to Redis as the sole mapping source. |
| `qlx_dmoverUseRedisMappingFallback` | `0` | When Fragdex mappings are enabled, consult Redis after Fragdex returns no mapping or an error. Fragdex mappings always take precedence. |
| `qlx_dmoverUseCvarDiscordBotToken` | `0` | Use the legacy `qlx_dmoverDiscordBotToken` value instead of fetching the token from Fragdex. |
| `qlx_dmoverDiscordBotToken` | empty | Legacy Discord bot token cvar; used only when `qlx_dmoverUseCvarDiscordBotToken` is `1`. |
| `qlx_fragdex_token_refresh_interval` | `3600` | Token refresh interval in seconds; `0` fetches only at plugin load. |

To switch entirely back to Redis mappings, set `qlx_dmoverUseFragdexMappings "0"`. To keep Fragdex primary but use old Redis mappings for missing/unavailable Fragdex records, set `qlx_dmoverUseRedisMappingFallback "1"`.

The `!link`, `!unlink` and `!links` commands manage Redis mappings only. They are unavailable in Fragdex-only mode; manage authoritative links in Fragdex. With the Redis fallback enabled, these commands can manage fallback entries, but they cannot override or remove a mapping that exists in Fragdex.

For the legacy token source, set both:

```text
set qlx_dmoverUseCvarDiscordBotToken "1"
set qlx_dmoverDiscordBotToken "<Discord bot token>"
```

Do not expose either the Discord token or Fragdex API key in chat or logs. Keep the API key restricted to the minimum IP range and rotate it if exposed.

## Verification

- Link a test Steam ID to a Discord ID in Fragdex, then run `!whois <steam_id>` and `!move teams`; the returned mapping should come from Fragdex.
- With Fragdex mapping enabled and Redis fallback disabled, leave a mapping only in Redis. QL Mover should warn that Fragdex has no mapping and skip that player.
- Enable `qlx_dmoverUseRedisMappingFallback "1"` with the same test data. The Redis-only mapping should then be used.
- Stop or block Fragdex temporarily. With fallback disabled, lookups should log the API failure and skip the player without affecting server availability; with fallback enabled, an existing Redis mapping should be used.
- Set `qlx_dmoverUseFragdexMappings "0"` to verify the legacy Redis-only mode.
