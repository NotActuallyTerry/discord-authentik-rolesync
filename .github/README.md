# Discord Roles to Authentik Groups sync

This is a python application that will sync Discord Roles to Authentik Groups.

For this to work you need to:
1. Implement the [Discord Authentik Identity Provider](https://docs.goauthentik.io/users-sources/sources/social-logins/discord/)
2. Create a User Property Mapping that stores their Discord ID as an attribute, under `attributes.discord.id`
3. Add a `discord_role_id` attribute to each Authentik group you'd like to sync, e.g. `discord_role_id: "940183386595655771"`
NOTE: Make sure to enclose the ID in quotes, otherwise Authentik will round the number & break the link!
4. Create an Authentik service account & assign them the following permissions:
   - `Add user to group`
   - `Remove user from group`
   - `Can view Group`
   - `Can view User`
5. Create an API key (under Tokens and App passwords), assigning it to the above service account
6. Create a Discord Application ([here](https://discord.com/developers/applications)) & add the bot to your server.
   - Make sure it has the Server Members intent, otherwise it won't receive role membership updates

## Example config

```yaml
      DISCORD_BOT_TOKEN: MZ1yGvKTjE0rY0cV8i47CjAa.uRHQPq.Xb1Mk2nEhe-4iUcrGOuegj57zMC
      DISCORD_GUILD_ID: 444746940761243652
      AUTHENTIK_HOST: https://authentik-instance/api/v3
      AUTHENTIK_API_KEY: I2khOuRBfgZzohV8fQAbJcRXYIJIuXKWe1Q88OTqD8lkOcEoqcwz7z9XIoGJ
```
