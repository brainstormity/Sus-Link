# Using Sus Link

[Back to README](../README.md)

## Scan a link

1. Right-click a message containing a link.
2. Choose **Apps → Sus Link Checker**.
3. If the message has several links, pick one from the selector.
4. The command confirms: “Inspecting link. Your report will be sent to you by DM once ready.”
5. Open the bot’s DM to read the finished report.

The report header links back to the original checked message. The report includes a verdict, an overall risk score, AI confidence, and recommended action. The captured screenshot appears directly on the report when available. The Evidence button is currently hidden. To run another scan, use **Apps → Sus Link Checker** again.

Only the bot owner can use it. The command acknowledgement is ephemeral, including in DMs with other people and group DMs. Finished reports are ordinary private messages sent directly by the bot, with the screenshot attached. One scan runs at a time; there are no progress edits.

A risk score is not a probability or a guarantee of safety. If the page is missing, blocked, empty, or AI analysis is unavailable, the report explains that under **Inspection limits**. Without sufficient evidence the verdict remains **Inconclusive**; concrete warning signals can still justify **Suspicious** or **High risk** despite limited coverage. See [scanning limitations](technical-details.md).

## Preview the report layout

Run **`/sample-report`** for an instant, private preview using the same container, score card, and screenshot layout as a real report. The header says **SAMPLE REPORT**. Optionally choose Low risk, Suspicious, High risk, or Inconclusive using the `verdict` option. This owner-only command uses fictional data and a locally drawn example page; it makes no Instabox or Gemini requests and saves no scan record.

After adding this command, restart the bot and DM it `!sync` once to register it manually.

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
| Report cannot be delivered | Enable direct messages from the bot, then run the command again. |
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

The last three options must be run in a server. Reading ordinary `!` commands in server messages requires Message Content Intent; DM `!sync` works with the intent disabled. Sync confirmations are normal private DM messages; finished scan reports arrive as ordinary private DMs.
