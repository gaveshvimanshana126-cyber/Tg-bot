const TelegramBot = require('node-telegram-bot-api');
const https = require('https');
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');

const TOKEN = process.env.BOT_TOKEN;
if (!TOKEN) { console.error('BOT_TOKEN not set!'); process.exit(1); }

const API_KEY = 'chama_api_3d72ec318aaf94313008eff7e38f3fbe';
const API_BASE = 'https://api.chamindu.site/api/v1/movies/lksub';

const bot = new TelegramBot(TOKEN, { polling: true });
console.log('🤖 Bot started...');

const userState = {};

// ───────── DOWNLOAD FILE HELPER ─────────
function downloadFile(url) {
  return new Promise((resolve, reject) => {
    const tmpPath = path.join(os.tmpdir(), 'sub_' + Date.now() + '.zip');
    const file = fs.createWriteStream(tmpPath);
    const proto = url.startsWith('https') ? https : http;

    function doRequest(reqUrl, redirectCount = 0) {
      if (redirectCount > 5) return reject(new Error('Too many redirects'));
      proto.get(reqUrl, {
        headers: {
          'User-Agent': 'Mozilla/5.0',
          'Referer': 'https://www.lksubs.com/'
        }
      }, (res) => {
        if (res.statusCode === 301 || res.statusCode === 302 || res.statusCode === 307) {
          const loc = res.headers.location;
          if (!loc) return reject(new Error('Redirect with no location'));
          const newProto = loc.startsWith('https') ? https : http;
          newProto.get(loc, { headers: { 'User-Agent': 'Mozilla/5.0' } }, (res2) => {
            res2.pipe(file);
            file.on('finish', () => { file.close(); resolve(tmpPath); });
            file.on('error', reject);
          }).on('error', reject);
          return;
        }
        if (res.statusCode !== 200) return reject(new Error('HTTP ' + res.statusCode));
        res.pipe(file);
        file.on('finish', () => { file.close(); resolve(tmpPath); });
        file.on('error', reject);
      }).on('error', reject);
    }
    doRequest(url);
  });
}

// ───────── API HELPERS ─────────
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
`👋 හෙලෝ *${name}*!

🎬 *Sinhala Subtitles Bot* එකට ඔයොස් වදිල ❤️

Movie name ලියලා send කරන්න — Sinhala subtitles හොයලා දෙනවා!

*උදා:* Avatar, Avengers, Inception

📋 Commands:
/start - Bot start
/help - Help
/id - Chat ID`,
    { parse_mode: 'Markdown' }
  );
});

// ───────── /help ─────────
bot.onText(/\/help/, (msg) => {
  bot.sendMessage(msg.chat.id,
`📋 *Help*

🔍 Movie name ලියලා send කරන්න
Bot එක lksubs.com ලෙස Sinhala subtitles search කරනවා

*උදා:* Avatar, Spider-Man, Oppenheimer

📥 Result list ලෙස subtitle ZIP direct download කරගන්නත් පුළුවන්!`,
    { parse_mode: 'Markdown' }
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

  const searching = await bot.sendMessage(chatId, `🔍 *"${query}"* සෙවිල්ලා... ⏳`, { parse_mode: 'Markdown' });

  try {
    const results = await searchSubs(query);

    if (!results.length) {
      await bot.editMessageText(
        `😔 *"${query}"* සඳහා Sinhala subtitles හමු නොවුණා.\nවෙනත් title එකක් try කරන්න.`,
        { chat_id: chatId, message_id: searching.message_id, parse_mode: 'Markdown' }
      );
      return;
    }

    userState[chatId] = { results };

    const keyboard = results.slice(0, 5).map((r, i) => [{
      text: `${i + 1}. ${r.title.replace(/ Sinhala Subtitles.*$/i, '').trim()}`,
      callback_data: `sub_${i}`
    }]);

    await bot.editMessageText(
      `✅ *${results.length}* result(s) found!\n\nSelect a movie:`,
      {
        chat_id: chatId,
        message_id: searching.message_id,
        parse_mode: 'Markdown',
        reply_markup: { inline_keyboard: keyboard }
      }
    );

  } catch (err) {
    console.error('Search error:', err.message);
    await bot.editMessageText(`❌ Error: ${err.message}`, { chat_id: chatId, message_id: searching.message_id });
  }
});

// ───────── CALLBACK ─────────
bot.on('callback_query', async (query) => {
  const chatId = query.message.chat.id;
  const msgId = query.message.message_id;
  const data = query.data;

  await bot.answerCallbackQuery(query.id);

  // ── Movie select ──
  if (data.startsWith('sub_')) {
    const idx = parseInt(data.replace('sub_', ''));
    const state = userState[chatId];
    if (!state || !state.results[idx]) return;

    const selected = state.results[idx];

    await bot.editMessageText(`⏳ Details loading...`, { chat_id: chatId, message_id: msgId });

    try {
      const detail = await getSubDetails(selected.link);
      if (!detail) throw new Error('Details load failed');

      // Store detail for download
      userState[chatId].detail = detail;
      userState[chatId].selectedIdx = idx;

      const title = selected.title.replace(/ Sinhala Subtitles.*$/i, '').trim();
      const genres = (detail.genres || []).join(', ');

      // Build download buttons
      const dlButtons = (detail.downloads || []).map((d, i) => {
        const isZip = d.link.includes('.zip') || d.name.toLowerCase().includes('subtitle');
        const icon = isZip ? '📥 Subtitle ZIP' : '🎬 Movie File';
        return [{ text: `${icon} — ${d.name.replace(/[\[\]]/g, '').trim().slice(0, 40)}`, callback_data: `dl_${i}` }];
      });

      // Add lksubs link button
      dlButtons.push([{ text: '🌐 lksubs.com ලෙස බලන්න', url: selected.link }]);

      const caption =
`🎬 *${title}*

🎭 *Genres:* ${genres || 'N/A'}
⭐ *IMDb:* ${detail.imdb || 'N/A'}
🗣️ *Language:* Sinhala Subtitles

📥 *Download:*`;

      await bot.deleteMessage(chatId, msgId).catch(() => {});

      if (detail.image) {
        await bot.sendPhoto(chatId, detail.image, {
          caption,
          parse_mode: 'Markdown',
          reply_markup: { inline_keyboard: dlButtons }
        });
      } else {
        await bot.sendMessage(chatId, caption, {
          parse_mode: 'Markdown',
          reply_markup: { inline_keyboard: dlButtons }
        });
      }

    } catch (err) {
      console.error('Detail error:', err.message);
      await bot.sendMessage(chatId, `❌ Error: ${err.message}\n\n🔗 ${selected.link}`);
    }
  }

  // ── Download button ──
  if (data.startsWith('dl_')) {
    const dlIdx = parseInt(data.replace('dl_', ''));
    const state = userState[chatId];
    if (!state || !state.detail) return;

    const dl = state.detail.downloads[dlIdx];
    if (!dl) return;

    const isZip = dl.link.includes('.zip') || dl.name.toLowerCase().includes('subtitle');

    if (isZip) {
      // Send ZIP file directly
      const statusMsg = await bot.sendMessage(chatId, `📥 Subtitle ZIP download කරනවා... ⏳`);
      try {
        const filePath = await downloadFile(dl.link);
        const stats = fs.statSync(filePath);
        const sizeMB = (stats.size / 1024 / 1024).toFixed(2);

        await bot.editMessageText(`📦 Sending file (${sizeMB} MB)...`, {
          chat_id: chatId, message_id: statusMsg.message_id
        });

        await bot.sendDocument(chatId, filePath, {
          caption: `📥 *Sinhala Subtitle ZIP*\n\n${dl.name}`,
          parse_mode: 'Markdown'
        });

        fs.unlinkSync(filePath);
        await bot.deleteMessage(chatId, statusMsg.message_id).catch(() => {});

      } catch (err) {
        console.error('Download error:', err.message);
        await bot.editMessageText(
          `❌ Download failed.\n\n📎 Manual download:\n${dl.link}`,
          { chat_id: chatId, message_id: statusMsg.message_id }
        );
      }
    } else {
      // Movie file — send link
      await bot.sendMessage(chatId,
        `🎬 *Movie File Download Link:*\n\n[${dl.name}](${dl.link})`,
        { parse_mode: 'Markdown', disable_web_page_preview: true }
      );
    }
  }
});

bot.on('polling_error', (err) => console.error('Polling error:', err.message));
