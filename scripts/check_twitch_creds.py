import asyncio
import os

from twitchbuddy.twitch_api import TwitchAPI


async def main():
    print("Checking environment variables...")
    print("TWITCH_CLIENT_ID present:", bool(os.getenv("TWITCH_CLIENT_ID")))
    print("TWITCH_CLIENT_SECRET present:", bool(os.getenv("TWITCH_CLIENT_SECRET")))
    print("TWITCH_CHANNEL:", os.getenv("TWITCH_CHANNEL"))

    api = TwitchAPI()

    try:
        await api._acquire_app_token()
        print("Acquired app token: ", bool(api._access_token))
    except Exception as exc:
        print("Token acquisition failed:", repr(exc))
        return

    try:
        channel = os.getenv("TWITCH_CHANNEL") or "storygirl"
        user = await api.get_user_by_login(channel)
        if user:
            print(
                "User lookup succeeded: id=",
                user.get("id"),
                "login=",
                user.get("login"),
            )
        else:
            print("User lookup: not found for", channel)
    except Exception as exc:
        print("User lookup failed:", repr(exc))


if __name__ == "__main__":
    asyncio.run(main())
