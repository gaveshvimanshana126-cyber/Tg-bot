const TelegramBot = require('node-telegram-bot-api');

const TOKEN = process.env.BOT_TOKEN;
if (!TOKEN) { console.error('BOT_TOKEN not set!'); process.exit(1); }

const API_KEY = 'chama_api_3d72ec318aaf94313008eff7e38f3fbe';
const API_BASE = 'https://api.chamindu.site/api/v1/movies/lksub';

const bot = new TelegramBot(TOKEN, { polling: true });

console.log('🤖 Bot started...');

// User state tracking (inline keyboard callbacks)
const userState = {};

// ───────── HELPERS ─────────
async function searchSubs(query) {
  const url = `${API_BASE}/search?q=${encodeURIComponent(query)}&api_key=${API_KEY}`;
  const res = await fetch(url);
  const data = await res.json();
  if (!data.status || !data.data?.length) return [];
  return data.data;
}

async function getSubDetails(link) {
  const url = `${API_BASE}/infodl?q=${encodeURIComponent(link)}&api_key=${API_KEY}`;
  const res = await fetch(url);
  const data = await res.json();
  if (!data.status || !data.data) return null;
  return data.data;
}

// ───────── /start ─────────
bot.onText(/\/start/, (msg) => {
  const name = msg.from.first_name || 'යාළුවා';
  bot.sendMessage(msg.chat.id,
`👋 හෙලෝ *${name}*\\!

🎬 *Sinhala Subtitles Bot* එකට ඔයොස් වදිල ❤️

සිංහල උපසිරැසි ගන්න movie name ලියලා send කරන්න\\!

*උදා:* Avatar, Avengers, Inception

📋 *Commands:*
/start \\- Bot start
/help \\- Help
/id \\- Chat ID`,
    { parse_mode: 'MarkdownV2' }
  );
});

// ───────── /help ─────────
bot.onText(/\/help/, (msg) => {
  bot.sendMessage(msg.chat.id,
`📋 *Help*

🔍 Movie name ලියලා send කරන්න
Bot එක lksubs\\.com ලෙස Sinhala subtitles search කරනවා

*උදා:* Avatar, Spider\\-Man, Oppenheimer

/id \\- ඔයාගේ Chat ID`,
    { parse_mode: 'MarkdownV2' }
  );
});

// ───────── /id ─────────
bot.onText(/\/id/, (msg) => {
  bot.sendMessage(msg.chat.id,
    `🆔 Chat ID: \`${msg.chat.id}\`\nUser ID: \`${msg.from.id}\``,
    { parse_mode: 'Markdown' }
  );
});

// ───────── TEXT → SEARCH ─────────
bot.on('message', async (msg) => {
  if (!msg.text || msg.text.startsWith('/')) return;

  const chatId = msg.chat.id;
  const query = msg.text.trim();

  const searching = await bot.sendMessage(chatId, `🔍 "${query}" සෙවිල්ලා\\.\\.\\. ⏳`, { parse_mode: 'MarkdownV2' });

  try {
    const results = await searchSubs(query);

    if (!results.length) {
      await bot.editMessageText(
        `😔 "${query}" සඳහා Sinhala subtitles හමු නොවුණා\\.\nවෙනත් title එකක් try කරන්න\\.`,
        { chat_id: chatId, message_id: searching.message_id, parse_mode: 'MarkdownV2' }
      );
      return;
    }

    // Store results in state
    userState[chatId] = { results };

    // Build inline keyboard (max 5 results)
    const keyboard = results.slice(0, 5).map((r, i) => [{
      text: `${i + 1}. ${r.title.replace(/ Sinhala Subtitles.*$/i, '').trim()}`,
      callback_data: `sub_${i}`
    }]);

    await bot.editMessageText(
      `✅ *${results.length}* result\\(s\\) found\\!\n\nSelect a movie:`,
      {
        chat_id: chatId,
        message_id: searching.message_id,
        parse_mode: 'MarkdownV2',
        reply_markup: { inline_keyboard: keyboard }
      }
    );

  } catch (err) {
    console.error('Search error:', err.message);
    await bot.editMessageText(
      `❌ Error: ${err.message}`,
      { chat_id: chatId, message_id: searching.message_id }
    );
  }
});

// ───────── CALLBACK → DETAIL ─────────
bot.on('callback_query', async (query) => {
  const chatId = query.message.chat.id;
  const msgId = query.message.message_id;
  const data = query.data;

  await bot.answerCallbackQuery(query.id);

  if (data.startsWith('sub_')) {
    const idx = parseInt(data.replace('sub_', ''));
    const state = userState[chatId];
    if (!state || !state.results[idx]) return;

    const selected = state.results[idx];

    await bot.editMessageText(
      `⏳ Loading details\\.\\.\\.`,
      { chat_id: chatId, message_id: msgId, parse_mode: 'MarkdownV2' }
    );

    try {
      const detail = await getSubDetails(selected.link);
      if (!detail) throw new Error('Details load failed');

      // Build downloads text
      const dlLines = (detail.downloads || []).map((d, i) =>
        `${i + 1}\\. [${escMd(d.name)}](${escMd(d.link)})`
      ).join('\n');

      const genres = (detail.genres || []).map(escMd).join(', ');
      const story = escMd((detail.story || '').split('\n')[0].trim().slice(0, 200));
      const title = escMd(selected.title.replace(/ Sinhala Subtitles.*$/i, '').trim());

      const caption =
`🎬 *${title}*

🎭 *Genres:* ${genres || 'N/A'}
⭐ *IMDb:* ${escMd(detail.imdb || 'N/A')}
🗣️ *Language:* Sinhala Subtitles

📖 ${story}

📥 *Downloads:*
${dlLines || 'No downloads found'}

🔗 [lksubs\\.com ලෙස බලන්න](${escMd(selected.link)})`;

      // Send with poster image
      if (detail.image) {
        await bot.deleteMessage(chatId, msgId).catch(() => {});
        await bot.sendPhoto(chatId, detail.image, {
          caption,
          parse_mode: 'MarkdownV2'
        });
      } else {
        await bot.editMessageText(caption, {
          chat_id: chatId,
          message_id: msgId,
          parse_mode: 'MarkdownV2',
          disable_web_page_preview: false
        });
      }

    } catch (err) {
      console.error('Detail error:', err.message);
      await bot.editMessageText(
        `❌ Details load failed: ${err.message}\n\n🔗 Manual: ${selected.link}`,
        { chat_id: chatId, message_id: msgId }
      );
    }
  }
});

// ───────── ESCAPE MARKDOWN V2 ─────────
function escMd(text) {
  return String(text || '').replace(/([_*\[\]()~`>#+\-=|{}.!\\])/g, '\\$1');
}

bot.on('polling_error', (err) => console.error('Polling error:', err.message));
