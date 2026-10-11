const TelegramBot = require('node-telegram-bot-api');

const TOKEN = process.env.BOT_TOKEN;
if (!TOKEN) { console.error('BOT_TOKEN not set!'); process.exit(1); }

const bot = new TelegramBot(TOKEN, { polling: true });

console.log('🤖 Bot started...');

// /start
bot.onText(/\/start/, (msg) => {
  const name = msg.from.first_name || 'Friend';
  bot.sendMessage(msg.chat.id,
    `👋 හෙලෝ ${name}!\n\nMCF Bot එකට ඔයොස් වදිල ❤️\n\nCommands:\n/start — Bot start\n/help — Help\n/id — ඔයාගේ Chat ID`
  );
});

// /help
bot.onText(/\/help/, (msg) => {
  bot.sendMessage(msg.chat.id,
    `📋 *Help*\n\n/start — Bot start කරන්න\n/id — ඔයාගේ Chat ID\n/echo [text] — Text repeat කරනවා`,
    { parse_mode: 'Markdown' }
  );
});

// /id
bot.onText(/\/id/, (msg) => {
  bot.sendMessage(msg.chat.id,
    `🆔 ඔයාගේ Chat ID: \`${msg.chat.id}\`\nUser ID: \`${msg.from.id}\``,
    { parse_mode: 'Markdown' }
  );
});

// /echo
bot.onText(/\/echo (.+)/, (msg, match) => {
  bot.sendMessage(msg.chat.id, `🔁 ${match[1]}`);
});

// Any message
bot.on('message', (msg) => {
  if (msg.text && !msg.text.startsWith('/')) {
    bot.sendMessage(msg.chat.id, `✅ Got it: "${msg.text}"\n\nHelp: /help`);
  }
});

bot.on('polling_error', (err) => console.error('Polling error:', err.message));
