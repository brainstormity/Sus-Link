# Using Sus Link

[Back to README](../README.md)

## Scan a link

1. Right-click a message containing a link.
2. Choose **Apps → Sus Link Checker**.
3. If the message has several links, pick one from the selector.
4. Watch the private checklist: ✅ means complete; ⏳ means pending or running.

The report includes a verdict, an observed-signal risk score, AI confidence, and recommended action. Use **Evidence**, **Screenshot**, **Full report**, or **Rescan** for more detail. Buttons expire after ten minutes; run the command again afterward.

Only the bot owner can use it. Reports are ephemeral, including in DMs with other people and group DMs. One scan runs at a time. Checklist updates are spaced at least five seconds apart.

A risk score is not a probability or a guarantee of safety. Failed page loads, access challenges, or unavailable AI produce an **Inconclusive** verdict. See [scanning limitations](technical-details.md).

## If the command is missing

- Start the bot and send `!sync` in a DM directly with it.
- Enable **User Install** in the Developer Portal before syncing.
- For DMs with other people, install using **Add to my apps**. A server install alone is insufficient.
- Allow Discord time to display newly synced commands.

Follow the [Discord setup guide](discord-setup.md) to check your settings.

## Other common issues

| Issue | What to check |
| --- | --- |
| Only the bot owner can use Sus Link | Use the account that owns the Discord application. Team developers and admins are also recognized for team-owned apps. |
| A scan is already running | Wait for the current scan to finish. |
| First scan takes longer | Instabox is creating the machine and installing the browser. |
| AI is unavailable | Check your Gemini key, project quotas, and model availability. Captured evidence is still returned where available. |
| Machine name is already in use | Use a separate `INSTABOX_MACHINE_NAME`; Sus Link will not take over another application's machine. |
| Database is still open | Stop the existing bot process before restarting. |

## Manual sync options

Send `!sync` in the bot's DM to sync globally. Commands never sync automatically at startup.

The original advanced options are available:

| Command | Action |
| --- | --- |
| `!sync <guild_id> ...` | Sync specified guilds |
| `!sync ~` | Sync the current guild |
| `!sync *` | Copy global commands to the current guild and sync |
| `!sync ^` | Remove the current guild's commands |

The last three options must be run in a server. Reading ordinary `!` commands in server messages requires Message Content Intent; DM `!sync` works with the intent disabled. Sync confirmations are normal private DM messages; scan reports use ephemeral interaction replies.
