import asyncio
import logging
import os

import authentik_client
import discord

dt_fmt = '%Y-%m-%d %H:%M:%S'
formatter = logging.Formatter('[{asctime}] [{levelname:<8}] {name}: {message}', dt_fmt, style='{')

handler = logging.StreamHandler()
handler.setFormatter(formatter)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(handler)

AuthentikConfig = authentik_client.Configuration(
    host=os.environ["AUTHENTIK_HOST"],
    access_token=os.environ["AUTHENTIK_API_KEY"]
)

AuthentikClient = authentik_client.ApiClient(AuthentikConfig)
AuthentikCoreApi = authentik_client.CoreApi(AuthentikClient)
AuthentikSourcesApi = authentik_client.SourcesApi(AuthentikClient)

DISCORD_GUILD_ID: int = int(os.environ["DISCORD_GUILD_ID"])

# We require the Members intent to receive updates to role membership
intents = discord.Intents.default()
intents.members = True

DiscordClient = discord.Client(intents=intents)


def get_linked_groups(client: authentik_client.CoreApi) -> list:
    """
    Get all Authentik groups that have the required attribute for linking to a Discord role
    :param client: A CoreApi instance configured for your Authentik instance
    :rtype: list
    :return: A list of groups with the required attribute
    """

    # We could keep paginating until we cover all groups
    # ooooor we could just search for 250 groups
    groups = client.core_groups_list(
        page_size=250,
        include_users=False
    )

    valid_groups = []

    for group in groups.results:
        try:
            if group.attributes["discord_role_id"]:
                valid_groups.append(group)
        except KeyError:

            # If the group doesn't have the required attribute, it'll throw a KeyError
            # We can just catch and kill the error :)
            pass

    return valid_groups


def get_linked_role(client: discord.client.Client, group: authentik_client.Group) -> discord.Role | None:
    """
    Get the Discord role that is linked to an Authentik group
    :param client: A Discord Client instance
    :param group: A dict containing an Authentik group with the attribute `discord_role_id`
    :rtype: discord.Role | None
    :return: The Discord role linked to the provided Authentik group
    """

    role_id = int(group.attributes["discord_role_id"])

    guild = client.get_guild(DISCORD_GUILD_ID)
    if guild is None:
        return None

    role = guild.get_role(role_id)
    if role is None:
        return None

    return role

def synchronise_group(client: authentik_client.CoreApi, sources: authentik_client.SourcesApi, groups: list) -> None:
    for group in groups:
        role = get_linked_role(client=DiscordClient, group=group)
        if not role:
            continue

        logger.info(f'Syncing Authentik group {group.name} with Discord role {role.name}')

        # Add users to the Authentik group if they're a part of the Discord role
        for discord_user in role.members:
            if discord_user.bot:
                continue

            authentik_user_conn = sources.sources_user_connections_oauth_list(
                source__slug="discord", search=str(discord_user.id)
            )

            if len(authentik_user_conn.results) == 0:
                continue

            authentik_user = AuthentikCoreApi.core_users_retrieve(
                id=authentik_user_conn.results[0].user
            )


            if discord_user.avatar is not None:
                current_url = None
                try:
                    current_url = authentik_user.attributes.get("avatar_url")
                except AttributeError:
                    pass

                if current_url is None or current_url != discord_user.avatar.with_size(256).url:
                    logger.info(f"Updating avatar for {discord_user.global_name}")

                    patched_user_request = authentik_client.models.PatchedUserRequest(
                        attributes={"avatar_url": discord_user.avatar.with_size(256).url},
                    )
                    AuthentikCoreApi.core_users_partial_update(id=authentik_user.pk,
                                                               patched_user_request=patched_user_request)

            if authentik_user.pk in group.users:
                continue

            logger.info(f"Adding {discord_user.global_name} to Authentik group {group.name}")

            user_acct_request = authentik_client.models.UserAccountRequest(
                pk=authentik_user.pk
            )

            client.core_groups_add_user_create(group.pk, user_acct_request)

        # Remove users from the Authentik group if they're not a part of the Discord role
        if group.users_obj:
            for authentik_user in group.users_obj:
                discord_id = authentik_user.attributes["discord"]["id"]

                if discord_id not in [user.id for user in role.members]:
                    discord_user = DiscordClient.get_guild(role.guild.id).get_member(discord_id)
                    logger.info("Removing %s (%s) from Authentik group %s" % (
                        authentik_user.username, discord_user.global_name, group.name))

                    user_acct_request = authentik_client.models.UserAccountRequest(
                        pk=authentik_user.results[0].pk
                    )

                    client.core_groups_remove_user_create(group.pk, user_acct_request)
    logger.info("Finished initial group sync")


@DiscordClient.event
async def on_ready():
    logger.info(f'We have logged in as {DiscordClient.user}')

    groups = get_linked_groups(client=AuthentikCoreApi)
    await asyncio.to_thread(synchronise_group, client=AuthentikCoreApi, sources=AuthentikSourcesApi, groups=groups)


@DiscordClient.event
async def on_member_update(previous: discord.Member, current: discord.Member):
    if current.bot:
        return

    # Create sets of the roles a user previously had and currently has
    # Makes it easy to check for differences between the two
    previous_roles = set(previous.roles)
    current_roles = set(current.roles)

    # If the sets are the same, the member update was for something else
    if current_roles == previous_roles:
        return

    # If a role exists in the current set but not the previous set, it was added
    added_roles = current_roles.difference(previous_roles)

    # If a role existed in the previous set but not the current set, it was removed
    removed_roles = previous_roles.difference(current_roles)

    authentik_user_id = AuthentikSourcesApi.sources_user_connections_oauth_list(
        source__slug="discord",
        search=str(previous.id))

    # If there isn't an Authentik user, we can't really action anything
    # They should've been cleaned up in the sync performed at launch
    if len(authentik_user_id.results) == 0:
        logger.debug("No authentik users found for Discord ID %s (%s)" % (previous.id, current.global_name))
        return

    authentik_user = AuthentikCoreApi.core_users_retrieve(
        id=authentik_user_id.results[0].user)

    if authentik_user.username is None:
        logger.debug("Authentik user with ID of % not found, something has gone terribly wrong"
                       % authentik_user_id.results[0].user)

    # Process all Discord roles the user has been added to
    if len(added_roles) > 0:
        for role in added_roles:
            authentik_group = AuthentikCoreApi.core_groups_list(
                attributes=('{"discord_role_id": "%s"}' % role.id))

            logger.info('Adding %s (%s) to Authentik group %s' % (
                    authentik_user.username, current.global_name, authentik_group.results[0].name))

            user_acct_request = authentik_client.models.UserAccountRequest(
                pk=authentik_user.pk
            )

            AuthentikCoreApi.core_groups_add_user_create(authentik_group.results[0].pk, user_acct_request)

    # Process all Discord roles the user was removed from
    if len(removed_roles) > 0:
        for role in removed_roles:
            authentik_group = AuthentikCoreApi.core_groups_list(
                attributes=('{"discord_role_id": "%s"}' % role.id))

            logger.info('Removing %s (%s) from Authentik group %s' % (
                    authentik_user.username, current.global_name, authentik_group.results[0].name))

            user_acct_request = authentik_client.models.UserAccountRequest(
                pk=authentik_user.pk
            )

            AuthentikCoreApi.core_groups_remove_user_create(authentik_group.results[0].pk, user_acct_request)


@DiscordClient.event
async def on_user_update(previous: discord.User, current: discord.User):
    if previous.avatar != current.avatar:
        authentik_user_id = AuthentikSourcesApi.sources_user_connections_oauth_list(
            source__slug="discord",
            search=str(previous.id))

        if len(authentik_user_id.results) == 0:
            logger.debug("No authentik users found for Discord ID %s (%s)" % (previous.id, current.global_name))
            return

        if not current.avatar:
            logger.info("%s (%s) removed their avatar. Removing avatar from Authentik..")
            patched_user_request = authentik_client.models.PatchedUserRequest(
                attributes={"avatar_url": None},
            )
            AuthentikCoreApi.core_users_partial_update(id=authentik_user_id.results[0].pk, patched_user_request=patched_user_request)
            return

        logger.info("%s (%s) updated their avatar. Updating avatar in Authentik..")
        patched_user_request = authentik_client.models.PatchedUserRequest(
            attributes={"avatar_url": current.avatar.with_size(256).url},
        )
        AuthentikCoreApi.core_users_partial_update(id=authentik_user_id.results[0].pk, patched_user_request=patched_user_request)


DiscordClient.run(token=os.environ["DISCORD_BOT_TOKEN"], log_handler=handler, log_formatter=formatter)
