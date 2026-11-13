import datetime

import pytest

import vector
from vector.ext.commands.core import StringView


def test_embed_renders_vector_markdown():
    e = vector.Embed(title="Stats", url="https://example.com", description="All good", colour=vector.Colour.blurple(),
                     timestamp=datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc))
    e.set_author(name="Kit")
    e.add_field(name="CPU", value="12%")
    e.add_field(name="RAM", value="1 GB")
    e.add_field(name="Notes", value="none", inline=False)
    e.set_footer(text="vector")
    e.set_image(url="attachment://chart.png")
    md = e.to_markdown()
    assert "### <color #59fcb3>**[Stats](<https://example.com>)**</color>" in md   # no unfurl, real heading
    assert "▍" not in md                                                          # no side line by default
    assert "> | CPU | RAM |\n> |---|---|\n> | 12% | 1 GB |" in md                        # inline fields -> table card
    assert "> **Notes**\n> none" in md
    assert "\n\n> -# vector • <t:1767225600:f>" in md                              # footer on its own line
    assert md.startswith("> -# Kit") and all(l.startswith(">") for l in md.split("\n") if l)
    assert e.attachment_names() == ["chart.png"]
    assert vector.Embed.from_dict(e.to_dict()) == e


def test_permissions_discord_names_and_vector_names():
    p = vector.Permissions(kick_members=True, ban_members=True, embed_links=True)
    assert p.kick and p.kick_members and p.ban
    assert p.embed_links  # discord-only permission reads as granted
    assert not p.manage_roles
    ow = vector.PermissionOverwrite(send_messages=False, view_channel=True)
    allow, deny = ow.pair()
    assert allow.view_channel and deny.send_messages
    assert vector.PermissionOverwrite.from_pair(allow, deny) == ow


def test_colour_presets_and_parsing():
    assert vector.Color.red().value == 0xE74C3C
    assert vector.Colour.from_str("#ff0000").to_rgb() == (255, 0, 0)


def test_stringview_quotes():
    v = StringView('one "two words" three')
    words = []
    while not v.eof:
        v.skip_ws()
        words.append(v.get_quoted_word())
    assert words == ["one", "two words", "three"]


def test_utils_get_find():
    class O:
        def __init__(self, name, n):
            self.name, self.n = name, n

    items = [O("a", 1), O("b", 2)]
    assert vector.utils.get(items, name="b").n == 2
    assert vector.utils.find(lambda o: o.n == 1, items).name == "a"
    assert vector.utils.format_dt(datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc), "R") == "<t:1767225600:R>"


DISCORD_PY_NAMES = ['ActionRow', 'Activity', 'ActivityType', 'AllowedMentions', 'AppCommandContext', 'AppCommandOptionType', 'AppCommandPermissionType', 'AppCommandType', 'AppInfo', 'AppInstallParams', 'AppInstallationType', 'ApplicationFlags', 'Asset', 'Attachment', 'AttachmentFlags', 'AudioSource', 'AuditLogAction', 'AuditLogActionCategory', 'AuditLogChanges', 'AuditLogDiff', 'AuditLogEntry', 'AutoModAction', 'AutoModPresets', 'AutoModRule', 'AutoModRuleAction', 'AutoModRuleActionType', 'AutoModRuleEventType', 'AutoModRuleTriggerType', 'AutoModTrigger', 'AutoShardedClient', 'BanEntry', 'BaseActivity', 'BaseSoundboardSound', 'BotIntegration', 'Button', 'ButtonStyle', 'CallMessage', 'CategoryChannel', 'ChannelFlags', 'ChannelType', 'CheckboxComponent', 'CheckboxGroupComponent', 'CheckboxGroupOption', 'Client', 'ClientException', 'ClientStatus', 'ClientUser', 'Collectible', 'CollectibleType', 'Color', 'Colour', 'Component', 'ComponentType', 'ConnectionClosed', 'Container', 'ContentFilter', 'CustomActivity', 'DMChannel', 'DefaultAvatar', 'DeletedReferencedMessage', 'DiscordException', 'DiscordServerError', 'Embed', 'EmbedFlags', 'Emoji', 'Entitlement', 'EntitlementOwnerType', 'EntitlementType', 'EntityType', 'EventStatus', 'ExpireBehavior', 'ExpireBehaviour', 'FFmpegAudio', 'FFmpegOpusAudio', 'FFmpegPCMAudio', 'FFmpegProcessError', 'File', 'FileComponent', 'FileUploadComponent', 'Forbidden', 'ForumChannel', 'ForumLayoutType', 'ForumOrderType', 'ForumTag', 'Game', 'GatewayNotFound', 'GroupChannel', 'Guild', 'GuildPreview', 'GuildProductPurchase', 'GuildSticker', 'HTTPException', 'Integration', 'IntegrationAccount', 'IntegrationApplication', 'IntegrationTypeConfig', 'Intents', 'Interaction', 'InteractionCallbackActivityInstance', 'InteractionCallbackResponse', 'InteractionMessage', 'InteractionResponded', 'InteractionResponse', 'InteractionResponseType', 'InteractionType', 'InvalidData', 'Invite', 'InviteFlags', 'InviteTarget', 'InviteType', 'LabelComponent', 'Locale', 'LoginFailure', 'MFALevel', 'MediaGalleryComponent', 'MediaGalleryItem', 'MediaItemLoadingState', 'Member', 'MemberCacheFlags', 'MemberFlags', 'Message', 'MessageApplication', 'MessageFlags', 'MessageInteraction', 'MessageInteractionMetadata', 'MessageReference', 'MessageReferenceType', 'MessageSnapshot', 'MessageType', 'MissingApplicationID', 'NSFWLevel', 'NameplatePalette', 'NotFound', 'NotificationLevel', 'Object', 'Onboarding', 'OnboardingMode', 'OnboardingPrompt', 'OnboardingPromptOption', 'OnboardingPromptType', 'PCMAudio', 'PCMVolumeTransformer', 'PartialAppInfo', 'PartialEmoji', 'PartialIntegration', 'PartialInviteChannel', 'PartialInviteGuild', 'PartialMessage', 'PartialMessageable', 'PartialWebhookChannel', 'PartialWebhookGuild', 'PermissionOverwrite', 'Permissions', 'Poll', 'PollAnswer', 'PollLayoutType', 'PollMedia', 'PrimaryGuild', 'PrivacyLevel', 'PrivilegedIntentsRequired', 'PublicUserFlags', 'PurchaseNotification', 'RadioGroupComponent', 'RadioGroupOption', 'RateLimited', 'RawAppCommandPermissionsUpdateEvent', 'RawBulkMessageDeleteEvent', 'RawIntegrationDeleteEvent', 'RawMemberRemoveEvent', 'RawMessageDeleteEvent', 'RawMessageUpdateEvent', 'RawPollVoteActionEvent', 'RawPresenceUpdateEvent', 'RawReactionActionEvent', 'RawReactionClearEmojiEvent', 'RawReactionClearEvent', 'RawThreadDeleteEvent', 'RawThreadMembersUpdate', 'RawThreadUpdateEvent', 'RawTypingEvent', 'Reaction', 'ReactionType', 'Role', 'RoleFlags', 'RoleSubscriptionInfo', 'RoleTags', 'SKU', 'SKUFlags', 'SKUType', 'ScheduledEvent', 'SectionComponent', 'SelectDefaultValue', 'SelectDefaultValueType', 'SelectMenu', 'SelectOption', 'SeparatorComponent', 'SeparatorSpacing', 'SessionStartLimits', 'ShardInfo', 'SoundboardDefaultSound', 'SoundboardSound', 'SpeakingState', 'Spotify', 'StageChannel', 'StageInstance', 'StandardSticker', 'Status', 'StatusDisplayType', 'Sticker', 'StickerFormatType', 'StickerItem', 'StickerPack', 'StickerType', 'StreamIntegration', 'Streaming', 'Subscription', 'SubscriptionStatus', 'SyncWebhook', 'SyncWebhookMessage', 'SystemChannelFlags', 'Team', 'TeamMember', 'TeamMemberRole', 'TeamMembershipState', 'Template', 'TextChannel', 'TextDisplay', 'TextInput', 'TextStyle', 'Thread', 'ThreadMember', 'ThumbnailComponent', 'UnfurledMediaItem', 'User', 'UserFlags', 'VerificationLevel', 'VideoQualityMode', 'VoiceChannel', 'VoiceChannelEffect', 'VoiceChannelEffectAnimationType', 'VoiceChannelSoundEffect', 'VoiceClient', 'VoiceProtocol', 'VoiceState', 'Webhook', 'WebhookMessage', 'WebhookType', 'WelcomeChannel', 'WelcomeScreen', 'Widget', 'WidgetChannel', 'WidgetMember']


def test_every_discord_py_top_level_class_imports():
    missing = [n for n in DISCORD_PY_NAMES if not hasattr(vector, n)]
    assert not missing, missing


def test_stubs_import_subclass_and_fail_clearly():
    from vector import MemberFlags, MessageType, NotSupportedOnVector, StageChannel, Thread

    class MyThread(Thread):
        pass

    assert not isinstance(object(), Thread) and MessageType.default is MessageType.default
    assert MemberFlags().bot_http_interactions is False
    with pytest.raises(NotSupportedOnVector):
        StageChannel()
    from vector.ext import commands, tasks
    assert commands.FlagConverter and commands.BadFlagArgument and tasks.ExponentialBackoff


def test_vector_port_flags_and_fixes(tmp_path):
    from vector import port

    f = tmp_path / "bot.py"
    f.write_text('import discord\nfrom discord import Thread\nX = 123456789012345678\n'
                 'db = """\nCREATE TABLE g (GuildID integer PRIMARY KEY, id INTEGER, user_id INTEGER);\n"""\n'
                 'discord.Nonsense\n')
    found = port.check(str(f))
    msgs = " ".join(str(x) for x in found)
    assert "Nonsense has no Vector equivalent" in msgs and "Thread is a Discord-only" in msgs
    assert "hard-coded Discord ID" in msgs and "ID column declared INTEGER" in msgs
    port.check(str(f), fix=True)
    text = f.read_text()
    assert "GuildID TEXT PRIMARY KEY, id INTEGER, user_id TEXT" in text
