We're doing to try to create a Python-based Twitch-Bot that has the following primary functions:

1. Monitor Twitch Chat and apply RegEx pattern matching against incoming chat messages, with each regex pattern having a corresponding response or Alert Trigger. Chat triggers will inject chat responses directly into the channel's Twitch chat.
2. Scheduled broadcast messages that will be emitted to chat on a given schedule.
3. Monitor the Twitch API for incoming Twitch events, such as bit donations, subscriptions, raids and other Twitch events available through the relevant API.
4. Emit Alerts to an HTML Canvas that will be broadcast on localhost:3080 which can be subscribed to by an OBS Browser Source. Alerts will have the following components:
    a. A still graphic, GIF or video file which will be displayed on the canvas.
    b. An audio file which will play when the graphic is displayed.
    c. A text template with options for named arguments, which can be configured using curly braces {args} to specify arguments to the text file which will be replaced by appropriate data provided in ordered comma separated format which map to relevant Twitch API or chat values.
    d. A duration for the alert
    e. A fade-in/fade-out duration for the alert which over-rides the length of any playing media.
5. Provide a GUI for configuring chat responses and alerts with the following tabs:
    a. Twitch Connection Details
    b. Chat trigger configuration
    c. Chat scheduled message configuration
    d. Chat Alert trigger configuration
    e. Twitch API Event alert configuration.
    f. Media bin for audio content.
    g. Media bin for visual content.

The hope is that we can use Python for as much of this functionality as possible. We will use Python 3.12 as our baseline unless there is a dependency requiring a higher version of Python.

At a later date, we hope to capture chat messages to a column-store database for statistical analysis as follows:

1. Track user timeout count
2. Track user deleted message count
3. Track user automod held message count
4. Track number of streams in which the user has chatted.
5. Track number of chat messages sent by the chatter.
6. Provide a list of streams in the configured channel's follow list in which the chatter is banned.

These statistics would then be able to be displayed in an alert box in response to a chat command.

Regarding Python UI - I would like to use the simplest possible UI/UX framework, and am open to recommendations. Electron would be an acceptable fallback if there is no easy to use Python windowed application framework available.

If we need to configure a dynamic hosting site in order to emit alert HTML, FastAPI or a similar lightweight Python Web Server would be preferred, although Node.js would also be acceptable.