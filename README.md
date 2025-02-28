# ytdlp-bot README

# ytdlp-bot

This project is a Telegram bot that allows users to download videos from various platforms using the `yt-dlp` library. The bot is built using the `python-telegram-bot` library and is designed to be easy to set up and use.

## Features

- Download videos from links shared by users.
- Progress updates during the download process.
- Upload downloaded videos back to the user.

## Requirements

- Python 3.7 or higher
- Docker (optional, for containerized deployment)

## Installation

1. Clone the repository:

   ```
   git clone <repository-url>
   cd ytdlp-bot
   ```

2. Install the required Python packages:

   You can install the dependencies using pip:

   ```
   pip install -r requirements.txt
   ```

   Alternatively, you can build and run the Docker container:

   ```
   docker build -t ytdlp-bot .
   docker run -e TELEGRAM_TOKEN=<your-telegram-bot-token> ytdlp-bot
   docker run -v ytdlp-cache:/app/cache -e TELEGRAM_TOKEN=<your-telegram-bot-token> ytdlp-bot
   ```

## Usage

1. Set up your Telegram bot and get your bot token from [BotFather](https://core.telegram.org/bots#botfather).
2. Create a `.env` file in the project root and add your Telegram token:

   ```
   TELEGRAM_TOKEN=<your-telegram-bot-token>
   ```

3. Run the bot:

   ```
   python telegram-bot.py
   ```

4. Start chatting with your bot on Telegram!

## Contributing

Contributions are welcome! Please open an issue or submit a pull request for any improvements or bug fixes.

## License

This project is licensed under the MIT License. See the LICENSE file for details.