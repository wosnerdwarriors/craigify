import os
from typing import List, Optional, Dict


def resolve_bot_token(cli_token: Optional[str], cfg: Dict) -> Optional[str]:
    """Resolve bot token with precedence: CLI > config.json > DISCORD_BOT_TOKEN env var."""
    if cli_token:
        return cli_token
    cfg_token = (cfg or {}).get('discord', {}).get('bot_token') if cfg else None
    if cfg_token:
        return cfg_token
    return os.environ.get('DISCORD_BOT_TOKEN')


def resolve_channel_id(requested: Optional[str], cfg: Dict) -> Optional[str]:
    """Resolve a channel id from an alias or direct id.

    - If `requested` is an alias key present in `cfg['discord']['channel_aliases']`,
      return the mapped id.
    - If `requested` looks like an id (or is not found in aliases), return it unchanged.
    - If `requested` is None, fall back to `cfg['discord']['channel_id']` if present.
    """
    aliases = (cfg or {}).get('discord', {}).get('channel_aliases', {}) if cfg else {}
    if requested:
        if isinstance(aliases, dict) and requested in aliases:
            return aliases.get(requested)
        # do not accept raw numeric IDs from config; require aliases or explicit id passed
        return requested
    # no implicit fallback to singular channel_id; require explicit alias in CLI or config
    return None


def resolve_webhooks(raw: Optional[str], cfg: Dict) -> List[str]:
    """Resolve one or more webhook URLs.

    - `raw` may be a comma-separated list of aliases or URLs. If an entry matches
      a key in `cfg['discord']['webhook_aliases']`, the mapped URL is used.
    - If `raw` is None, fall back to `cfg['discord']['webhook_url']` if present.
    Returns a list (possibly empty) of webhook URLs.
    """
    webhooks = []
    aliases = (cfg or {}).get('discord', {}).get('webhook_aliases', {}) if cfg else {}
    if raw:
        for part in [p.strip() for p in raw.split(',') if p.strip()]:
            if isinstance(aliases, dict) and part in aliases:
                webhooks.append(aliases.get(part))
            else:
                webhooks.append(part)
    else:
        # do not fall back to a singular webhook_url in config; require aliases
        webhooks = []
    return webhooks
