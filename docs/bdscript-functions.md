# BDScript function reference (generated)

617 names. Status: blank = full, *partial* = works with a Vector-specific limit, *noop* = Discord-only concept, accepted and returns a neutral value so ported code keeps running.

## Control flow & script features

| Function | Status |
|---|---|
| `$allowMention` |  |
| `$allowRoleMentions` |  |
| `$allowUserMentions` |  |
| `$alternativeParsing` |  |
| `$and` |  |
| `$argsCheck` |  |
| `$async` |  |
| `$await` |  |
| `$botNode` |  |
| `$c` |  |
| `$catch` |  |
| `$checkCondition` |  |
| `$data` |  |
| `$defer` |  |
| `$disableInnerSpaceRemoval` |  |
| `$disableSpecialEscaping` |  |
| `$else` |  |
| `$elseif` |  |
| `$embedSuppressErrors` |  |
| `$enableDecimals` |  |
| `$endasync` |  |
| `$endif` |  |
| `$endloop` |  |
| `$endtry` |  |
| `$ephemeral` |  |
| `$error` |  |
| `$eval` |  |
| `$exec` | *partial*: disabled unless BDBot(allow_exec=True) |
| `$executionTime` |  |
| `$forEach` |  |
| `$get` |  |
| `$if` |  |
| `$let` |  |
| `$log` |  |
| `$logQuota` |  |
| `$loop` |  |
| `$nodeVersion` |  |
| `$nodeVersionComplex` |  |
| `$nomention` |  |
| `$onlyIf` |  |
| `$optOff` |  |
| `$or` |  |
| `$ping` |  |
| `$scriptLanguage` |  |
| `$stop` |  |
| `$suppressErrorLogging` |  |
| `$suppressErrors` |  |
| `$suppressErrorsComplex` |  |
| `$try` |  |
| `$tts` |  |
| `$unescape` |  |
| `$uptime` |  |
| `$var` |  |
| `$wait` |  |

## Message & text

| Function | Status |
|---|---|
| `$'randomString` |  |
| `$'randomText` |  |
| `$argCount` |  |
| `$byteCount` |  |
| `$charCount` |  |
| `$checkContains` |  |
| `$cropText` |  |
| `$editSplitText` |  |
| `$getTextSplitIndex` |  |
| `$getTextSplitLength` |  |
| `$isBoolean` |  |
| `$isInteger` |  |
| `$isMentioned` |  |
| `$isNumber` |  |
| `$isValidHex` |  |
| `$joinSplitText` |  |
| `$linesCount` |  |
| `$mentioned` |  |
| `$mentionedChannels` |  |
| `$mentionedRoles` |  |
| `$message` |  |
| `$messageComplex` |  |
| `$noMentionMessage` |  |
| `$noMentionMessageComplex` |  |
| `$numberSeparator` |  |
| `$randomString` |  |
| `$randomText` |  |
| `$removeContains` |  |
| `$removeLinks` |  |
| `$removeLinksComplex` |  |
| `$removeSplitTextElement` |  |
| `$repeatMessage` |  |
| `$replaceText` |  |
| `$sort` |  |
| `$splitText` |  |
| `$textSplit` |  |
| `$toLowercase` |  |
| `$toTitle` |  |
| `$toTitleCase` |  |
| `$toUppercase` |  |
| `$trimContent` |  |
| `$trimSpace` |  |
| `$url` |  |

## Math

| Function | Status |
|---|---|
| `$'random` |  |
| `$abs` |  |
| `$calculate` |  |
| `$ceil` |  |
| `$div` |  |
| `$divide` |  |
| `$floor` |  |
| `$math` |  |
| `$max` |  |
| `$min` |  |
| `$modulo` |  |
| `$multi` |  |
| `$random` |  |
| `$randomComplex` |  |
| `$round` |  |
| `$sqrt` |  |
| `$sub` |  |
| `$sum` |  |

## Date & time

| Function | Status |
|---|---|
| `$creationDate` |  |
| `$date` |  |
| `$dateStamp` |  |
| `$day` |  |
| `$formatTime` |  |
| `$getTimestamp` |  |
| `$getTimestampComplex` |  |
| `$hour` |  |
| `$minute` |  |
| `$month` |  |
| `$parseDuration` |  |
| `$parseTime` |  |
| `$second` |  |
| `$time` |  |
| `$year` |  |

## Embeds

| Function | Status |
|---|---|
| `$addContainer` |  |
| `$addField` |  |
| `$addMediaGallery` |  |
| `$addMediaGalleryItem` |  |
| `$addSection` |  |
| `$addSeparator` |  |
| `$addTextDisplay` |  |
| `$addThumbnail` |  |
| `$addTimestamp` |  |
| `$addTimestampComplex` |  |
| `$attachment` |  |
| `$author` |  |
| `$authorIcon` |  |
| `$authorURL` |  |
| `$color` |  |
| `$description` |  |
| `$editEmbedIn` |  |
| `$embeddedURL` |  |
| `$footer` |  |
| `$footerIcon` |  |
| `$getEmbedData` |  |
| `$image` |  |
| `$sendEmbedMessage` |  |
| `$thumbnail` |  |
| `$title` |  |

## Buttons, menus, modals, slash

| Function | Status |
|---|---|
| `$addActionRow` |  |
| `$addButton` |  |
| `$addSelectMenuOption` |  |
| `$addTextInput` |  |
| `$createSlashCommand` | *partial*: Vector slash commands are bot-wide; the server argument is accepted |
| `$customID` |  |
| `$editButton` |  |
| `$editSelectMenu` |  |
| `$editSelectMenuOption` |  |
| `$input` |  |
| `$interactionID` |  |
| `$interactionValues` |  |
| `$isSlash` |  |
| `$newModal` |  |
| `$newSelectMenu` |  |
| `$registerGuildCommands` |  |
| `$registerGuildCommandsComplex` |  |
| `$removeAllComponents` |  |
| `$removeAllComponentsComplex` |  |
| `$removeButtons` |  |
| `$removeButtonsComplex` |  |
| `$removeComponent` |  |
| `$selectMenuValues` |  |
| `$slashCommandsCount` |  |
| `$slashID` |  |
| `$slashIDComplex` |  |
| `$slashOption` |  |
| `$unregisterGuildCommands` |  |
| `$unregisterGuildCommandsComplex` |  |

## Users, members & condensed functions

| Function | Status |
|---|---|
| `$'randomMention` |  |
| `$'randomUser` |  |
| `$'randomUserID` |  |
| `$authorAvatar` |  |
| `$authorID` |  |
| `$authorOfMessage` |  |
| `$changeUsername` |  |
| `$changeUsernameWithID` |  |
| `$channel` |  |
| `$checkUserPerms` |  |
| `$client` |  |
| `$discriminator` |  |
| `$displayName` |  |
| `$displayNameComplex` |  |
| `$findUser` |  |
| `$getCustomStatus` |  |
| `$getUserStatus` |  |
| `$hasRole` |  |
| `$highestRole` |  |
| `$highestRoleComplex` |  |
| `$highestRoleWithPerms` |  |
| `$hypesquad` | *noop*: no HypeSquad on Vector |
| `$isAdmin` |  |
| `$isBooster` | *noop*: no boosting on Vector |
| `$isBot` |  |
| `$isTimedOut` |  |
| `$isUserDMEnabled` |  |
| `$lowestRole` |  |
| `$lowestRoleComplex` |  |
| `$lowestRoleWithPerms` |  |
| `$member` |  |
| `$nickname` |  |
| `$nicknameComplex` |  |
| `$randomMention` |  |
| `$randomUser` |  |
| `$randomUserID` |  |
| `$role` |  |
| `$server` |  |
| `$user` |  |
| `$userAvatar` |  |
| `$userBadges` | *noop*: no badges on Vector |
| `$userBanner` |  |
| `$userBannerColor` | *noop*: Vector profiles have no banner colour |
| `$userExists` |  |
| `$userID` |  |
| `$userInfo` |  |
| `$userJoined` |  |
| `$userJoinedDiscord` |  |
| `$username` |  |
| `$usernameComplex` |  |
| `$userPerms` |  |
| `$userRoles` |  |
| `$userServerAvatar` |  |

## Communities (servers), channels, roles, moderation

| Function | Status |
|---|---|
| `$'randomChannelID` |  |
| `$afkChannelID` | *noop* |
| `$afkTimeout` | *noop* |
| `$allMembersCount` |  |
| `$ban` |  |
| `$banComplex` |  |
| `$banID` |  |
| `$banIDComplex` |  |
| `$boostCount` | *noop*: no boosts on Vector |
| `$boostCountComplex` | *noop* |
| `$boostLevel` | *noop* |
| `$botLeave` |  |
| `$botLeaveComplex` |  |
| `$categoryChannels` |  |
| `$categoryCount` |  |
| `$categoryCountComplex` |  |
| `$categoryID` |  |
| `$channelCount` |  |
| `$channelExists` |  |
| `$channelID` |  |
| `$channelIDComplex` |  |
| `$channelIDFromName` |  |
| `$channelName` |  |
| `$channelNames` |  |
| `$channelPosition` |  |
| `$channelPositionComplex` |  |
| `$channelTopic` |  |
| `$channelTopicComplex` |  |
| `$channelType` |  |
| `$clear` |  |
| `$clearComplex` |  |
| `$colorRole` |  |
| `$communityBanner` |  |
| `$communityChannelExists` |  |
| `$communityCount` |  |
| `$communityDescription` |  |
| `$communityEmojis` |  |
| `$communityExists` |  |
| `$communityIcon` |  |
| `$communityID` |  |
| `$communityInfo` |  |
| `$communityInvite` |  |
| `$communityMembersCount` |  |
| `$communityName` |  |
| `$communityNames` |  |
| `$communityOwner` |  |
| `$createChannel` |  |
| `$createRole` |  |
| `$deleteChannels` |  |
| `$deleteChannelsByName` |  |
| `$deleteRole` |  |
| `$dmChannelID` |  |
| `$editChannelPerms` |  |
| `$emoteCount` |  |
| `$findChannel` |  |
| `$findRole` |  |
| `$getBanReason` |  |
| `$getBotInvite` |  |
| `$getInviteInfo` |  |
| `$getRoleColor` |  |
| `$getServerInvite` |  |
| `$getServerInviteComplex` |  |
| `$getSlowmode` |  |
| `$giveRole` |  |
| `$guildBanner` |  |
| `$guildExists` |  |
| `$guildID` |  |
| `$guildIDComplex` |  |
| `$isBanned` |  |
| `$isHoisted` |  |
| `$isMentionable` |  |
| `$isNSFW` |  |
| `$kick` |  |
| `$kickComplex` |  |
| `$kickMention` |  |
| `$lastPinTimestamp` |  |
| `$leaveCommunity` |  |
| `$membersCount` |  |
| `$membersCountComplex` |  |
| `$modifyChannel` |  |
| `$modifyChannelPerms` |  |
| `$modifyRole` |  |
| `$modifyRolePerms` |  |
| `$mute` |  |
| `$parentID` |  |
| `$parentIDComplex` |  |
| `$randomCategoryID` |  |
| `$randomChannelID` |  |
| `$randomCommunityID` |  |
| `$randomGuildID` |  |
| `$randomRoleID` |  |
| `$roleCount` |  |
| `$roleExists` |  |
| `$roleGrant` |  |
| `$roleID` |  |
| `$roleInfo` |  |
| `$roleName` |  |
| `$roleNames` |  |
| `$rolePerms` |  |
| `$rolePosition` |  |
| `$rulesChannelID` | *noop* |
| `$serverChannelExists` |  |
| `$serverCount` |  |
| `$serverDescription` |  |
| `$serverDescriptionComplex` |  |
| `$serverEmojis` |  |
| `$serverIcon` |  |
| `$serverIconComplex` |  |
| `$serverInfo` |  |
| `$serverName` |  |
| `$serverNames` |  |
| `$serverNamesComplex` |  |
| `$serverOwner` |  |
| `$serverOwnerComplex` |  |
| `$serverRegion` | *noop*: Vector has relays instead of regions |
| `$serverVerificationLvl` | *noop* |
| `$setUserRoles` |  |
| `$slowmode` | *partial*: stored; Vector has no slowmode yet |
| `$systemChannelID` |  |
| `$takeRole` |  |
| `$timeout` |  |
| `$unban` |  |
| `$unbanID` |  |
| `$unbanIDComplex` |  |
| `$unmute` |  |
| `$untimeout` |  |
| `$useChannel` |  |
| `$voiceUserLimit` |  |

## Messages, reactions, DMs, emoji, tickets, threads, webhooks

| Function | Status |
|---|---|
| `$addCmdReactions` |  |
| `$addEmoji` | *partial*: adds to the bot's own emoji pack |
| `$addMessageReactions` |  |
| `$addReactions` |  |
| `$botTyping` |  |
| `$channelSendMessage` |  |
| `$clearReactions` |  |
| `$closeTicket` |  |
| `$customEmoji` |  |
| `$deletecommand` |  |
| `$deleteIn` |  |
| `$deleteMessage` |  |
| `$dm` |  |
| `$dmComplex` |  |
| `$editIn` |  |
| `$editMessage` |  |
| `$editThread` | *partial* |
| `$emojiExists` |  |
| `$emojiName` |  |
| `$getAttachments` |  |
| `$getMessage` |  |
| `$getReactions` |  |
| `$isEmojiAnimated` |  |
| `$isMessageEdited` |  |
| `$isTicket` |  |
| `$lastMessageID` |  |
| `$messageEditedTimestamp` |  |
| `$messageID` |  |
| `$newTicket` |  |
| `$pinMessage` |  |
| `$pinMessageComplex` |  |
| `$publishMessage` | *noop*: no announcement channels on Vector |
| `$removeEmoji` | *partial* |
| `$repliedMessageID` |  |
| `$repliedMessageIDComplex` |  |
| `$reply` |  |
| `$replyComplex` |  |
| `$replyIn` |  |
| `$sendDM` |  |
| `$sendMessage` |  |
| `$startThread` | *partial*: creates a channel next to the parent |
| `$threadAddMember` | *partial* |
| `$threadMessageCount` | *partial* |
| `$threadRemoveMember` | *partial* |
| `$threadUserCount` | *partial* |
| `$unpinMessage` |  |
| `$userReacted` |  |
| `$webhookAvatarURL` | *noop*: Vector messages always use the bot's avatar |
| `$webhookColor` |  |
| `$webhookContent` |  |
| `$webhookCreate` |  |
| `$webhookDelete` |  |
| `$webhookDescription` |  |
| `$webhookFooter` |  |
| `$webhookSend` |  |
| `$webhookTitle` |  |
| `$webhookUsername` |  |

## Variables, leaderboards, cooldowns

| Function | Status |
|---|---|
| `$changeCooldownTime` |  |
| `$communityCooldown` |  |
| `$communityLeaderboard` |  |
| `$cooldown` |  |
| `$getChannelVar` |  |
| `$getCommunityVar` |  |
| `$getCooldown` |  |
| `$getLeaderboardPosition` |  |
| `$getLeaderboardValue` |  |
| `$getServerVar` |  |
| `$getUserVar` |  |
| `$getVar` |  |
| `$globalCooldown` |  |
| `$globalUserLeaderboard` |  |
| `$listVar` |  |
| `$resetChannelVar` |  |
| `$resetCommunityVar` |  |
| `$resetServerVar` |  |
| `$resetUserVar` |  |
| `$serverCooldown` |  |
| `$serverLeaderboard` |  |
| `$setChannelVar` |  |
| `$setCommunityVar` |  |
| `$setServerVar` |  |
| `$setUserVar` |  |
| `$setVar` |  |
| `$userLeaderboard` |  |
| `$varExistError` |  |
| `$varExists` |  |
| `$variablesCount` |  |

## JSON & HTTP

| Function | Status |
|---|---|
| `$httpAddHeader` |  |
| `$httpDelete` |  |
| `$httpGet` |  |
| `$httpGetHeader` |  |
| `$httpPatch` |  |
| `$httpPost` |  |
| `$httpPut` |  |
| `$httpRemoveHeader` |  |
| `$httpResult` |  |
| `$httpStatus` |  |
| `$json` |  |
| `$jsonArray` |  |
| `$jsonArrayAppend` |  |
| `$jsonArrayCount` |  |
| `$jsonArrayIndex` |  |
| `$jsonArrayPop` |  |
| `$jsonArrayReverse` |  |
| `$jsonArrayShift` |  |
| `$jsonArraySort` |  |
| `$jsonArrayUnshift` |  |
| `$jsonClear` |  |
| `$jsonExists` |  |
| `$jsonJoinArray` |  |
| `$jsonParse` |  |
| `$jsonPretty` |  |
| `$jsonSet` |  |
| `$jsonSetString` |  |
| `$jsonStringify` |  |
| `$jsonUnset` |  |

## Restrictions, bot info, callbacks, AI

| Function | Status |
|---|---|
| `$ai` |  |
| `$aiAgent` | *partial*: functions list is passed to the model as text |
| `$aiDecide` |  |
| `$aiDecideWithCtx` |  |
| `$aiQuota` |  |
| `$aiWithCtx` |  |
| `$alwaysReply` |  |
| `$awaitedCommand` |  |
| `$awaitedCommandError` |  |
| `$awaitFunc` |  |
| `$awaitReactions` |  |
| `$blackListCommunities` |  |
| `$blackListIDs` |  |
| `$blackListRoles` |  |
| `$blackListRolesIDs` |  |
| `$blackListServers` |  |
| `$blackListUsers` |  |
| `$botCommands` |  |
| `$botID` |  |
| `$botListDescription` | *noop* |
| `$botListHide` | *noop* |
| `$botOwnerID` |  |
| `$commandFolder` |  |
| `$commandInfo` |  |
| `$commandName` |  |
| `$commandsCount` |  |
| `$commandTrigger` |  |
| `$customImage` |  |
| `$enabled` |  |
| `$hostingExpireTime` | *noop* |
| `$hostingExpireTimeComplex` | *noop* |
| `$ignoreChannels` |  |
| `$ignoreLinks` |  |
| `$ignoreTriggerCase` |  |
| `$messageContains` |  |
| `$onBanAdd` |  |
| `$onBanRemove` |  |
| `$onInteraction` |  |
| `$onInteractionComplex` |  |
| `$onJoined` |  |
| `$onLeave` |  |
| `$onlyAdmin` |  |
| `$onlyBotChannelPerms` |  |
| `$onlyBotPerms` |  |
| `$onlyForCategories` |  |
| `$onlyForChannels` |  |
| `$onlyForCommunities` |  |
| `$onlyForIDs` |  |
| `$onlyForRoleIDs` |  |
| `$onlyForRoles` |  |
| `$onlyForServers` |  |
| `$onlyForUsers` |  |
| `$onlyIfMessageContains` |  |
| `$onlyNSFW` |  |
| `$onlyPerms` |  |
| `$onMessageDelete` |  |
| `$premiumExpireTime` | *noop*: no premium tier: everything is enabled |
| `$reaction` |  |
| `$sendNotification` |  |
| `$shardID` |  |
| `$shardIDComplex` |  |
| `$updateCommands` |  |
| `$usedEmoji` |  |

## Newer BDFD functions & music

| Function | Status |
|---|---|
| `$addButtonCV2` |  |
| `$addMentionableSelect` |  |
| `$addRoleSelect` |  |
| `$addUserSelect` |  |
| `$appendOptionSuggestion` | *partial*: collected; shown if the client supports autocomplete |
| `$autoCompleteOptionName` |  |
| `$autoCompleteOptionValue` |  |
| `$getMentionableSelectUserCount` |  |
| `$getMentionableSelectUserID` |  |
| `$getMentionableSelectUserIDs` |  |
| `$getRoleSelectRoleCount` |  |
| `$getRoleSelectRoleID` |  |
| `$getRoleSelectRoleIDs` |  |
| `$getSplitText` |  |
| `$getUserSelectUserCount` |  |
| `$getUserSelectUserID` |  |
| `$getUserSelectUserIDs` |  |
| `$joinVC` |  |
| `$joinVoice` |  |
| `$leaveVC` |  |
| `$leaveVoice` |  |
| `$onAutoComplete` |  |
| `$pauseSong` |  |
| `$playSong` |  |
| `$playTrack` |  |
| `$queue` |  |
| `$queueLength` |  |
| `$resumeSong` |  |
| `$say` |  |
| `$skipSong` |  |
| `$skipTrack` |  |
| `$songInfo` |  |
| `$stopMusic` |  |
| `$stopSong` |  |
| `$trackInfo` |  |

## Vector-only

| Function | Status |
|---|---|
| `$acceptInvite` |  |
| `$authorNpub` |  |
| `$blockUser` |  |
| `$botEmojis` |  |
| `$botNpub` |  |
| `$communityRelays` |  |
| `$containRaid` |  |
| `$createCommunity` |  |
| `$disappearIn` |  |
| `$emojiPacks` |  |
| `$expireIn` |  |
| `$grantAdmin` |  |
| `$grantChannelAccess` |  |
| `$hideMessage` |  |
| `$isDM` |  |
| `$isNpub` |  |
| `$isReadOnly` |  |
| `$joinCommunity` |  |
| `$npub` |  |
| `$pendingInvites` |  |
| `$relays` |  |
| `$revokeAdmin` |  |
| `$revokeChannelAccess` |  |
| `$sendMiniApp` |  |
| `$sendXdc` |  |
| `$setBotAbout` |  |
| `$setBotAvatar` |  |
| `$setBotBanner` |  |
| `$setBotName` |  |
| `$setBotStatus` |  |
| `$setChannelPrivate` |  |
| `$setChannelReadOnly` |  |
| `$setLocalNickname` |  |
| `$subscribeEmojiPack` |  |
| `$unblockUser` |  |
| `$unsubscribeEmojiPack` |  |
| `$uploadImage` |  |
| `$userAbout` |  |
