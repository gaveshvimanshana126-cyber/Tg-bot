const TelegramBot = require('node-telegram-bot-api');
const https = require('https');
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');

const TOKEN = process.env.BOT_TOKEN;
if (!TOKEN) { console.error('BOT_TOKEN not set!'); process.exit(1); }

const API_KEY = 'chama_api_3d72ec318aaf94313008eff7e38f3fbe';
const LKSUB_BASE   = 'https://api.chamindu.site/api/v1/movies/lksub';
const CINE_BASE    = 'https://api.chamindu.site/api/v1/movies/cinevibes';

const bot = new TelegramBot(TOKEN, { polling: true });
console.log('🤖 Bot started...');

const userState = {};

// ═══════════════════════════════════════
// DOWNLOAD FILE HELPER
// ═══════════════════════════════════════
function downloadFile(url, ext) {
  return new Promise((resolve, reject) => {
    const tmpPath = path.join(os.tmpdir(), 'dl_' + Date.now() + (ext || '.bin'));
    const file = fs.createWriteStream(tmpPath);

    function doGet(reqUrl, hops = 0) {
      if (hops > 5) return reject(new Error('Too many redirects'));
      const proto = reqUrl.startsWith('https') ? https : http;
      proto.get(reqUrl, {
        headers: { 'User-Agent': 'Mozilla/5.0', 'Referer': 'https://www.lksubs.com/' }
      }, (res) => {
        if ([301,302,307,308].includes(res.statusCode) && res.headers.location) {
          return doGet(res.headers.location, hops + 1);
        }
        if (res.statusCode !== 200) return reject(new Error(`HTTP ${res.statusCode} — Server rejected the request`));
        res.pipe(file);
        file.on('finish', () => { file.close(); resolve(tmpPath); });
        file.on('error', reject);
      }).on('error', reject);
    }
    doGet(url);
  });
}

// ═══════════════════════════════════════
// API HELPERS
// ═══════════════════════════════════════
async function lksubSearch(q) {
  const r = await fetch(`${LKSUB_BASE}/search?q=${encodeURIComponent(q)}&api_key=${API_KEY}`);
  const d = await r.json();
  return d.status ? (d.data || []).map(x => ({ ...x, _src: 'lksub' })) : [];
}
async function lksubDetail(link) {
  const r = await fetch(`${LKSUB_BASE}/infodl?q=${encodeURIComponent(link)}&api_key=${API_KEY}`);
  const d = await r.json();
  return d.status ? d.data : null;
}

async function cineSearch(q) {
  const r = await fetch(`${CINE_BASE}/search?q=${encodeURIComponent(q)}&api_key=${API_KEY}`);
  const d = await r.json();
  return d.status ? (d.data || []).map(x => ({ ...x, _src: 'cine' })) : [];
}
async function cineDetail(link) {
  const r = await fetch(`${CINE_BASE}/infodl?url=${encodeURIComponent(link)}&api_key=${API_KEY}`);
  const d = await r.json();
  return d.status ? d.data : null;
}

// ═══════════════════════════════════════
// /start
// ═══════════════════════════════════════
bot.onText(/\/start/, (msg) => {
  const name = msg.from.first_name || 'යාළුවා';
  bot.sendMessage(msg.chat.id,
`👋 හෙලෝ *${name}*!

🎬 *Sinhala Subtitles Bot* එකට ඔයොස් වදිල ❤️

Movie name ලියලා send කරන්න!

*Sources:*
📦 LKSubs — Subtitle ZIPs
🎞️ CineVibes — Movie + SRT files

*Commands:*
/start - Bot start
/help - Help
/id - Chat ID`,
    { parse_mode: 'Markdown' }
  );
});

bot.onText(/\/help/, (msg) => {
  bot.sendMessage(msg.chat.id,
`📋 *Help*

Movie name ලියලා send කරන්න
Bot එක LKSubs + CineVibes දෙකෙන්ම search කරනවා

📥 Subtitle ZIP / SRT direct download
🎬 Movie file links

*උදා:* Avatar, Badrinath, Oppenheimer`,
    { parse_mode: 'Markdown' }
  );
});

bot.onText(/\/id/, (msg) => {
  bot.sendMessage(msg.chat.id,
    `🆔 Chat ID: \`${msg.chat.id}\`\nUser ID: \`${msg.from.id}\``,
    { parse_mode: 'Markdown' }
  );
});

// ═══════════════════════════════════════
// TEXT → SEARCH (both sources)
// ═══════════════════════════════════════
bot.on('message', async (msg) => {
  if (!msg.text || msg.text.startsWith('/')) return;
  const chatId = msg.chat.id;
  const query = msg.text.trim();

  const statusMsg = await bot.sendMessage(chatId, `🔍 *"${query}"* සෙවිල්ලා... ⏳`, { parse_mode: 'Markdown' });

  try {
    const [lkResults, cineResults] = await Promise.allSettled([
      lksubSearch(query),
      cineSearch(query)
    ]);

    const lk   = lkResults.status === 'fulfilled'   ? lkResults.value   : [];
    const cine = cineResults.status === 'fulfilled' ? cineResults.value : [];
    const all  = [...cine, ...lk]; // CineVibes first (has movie files)

    if (!all.length) {
      await bot.editMessageText(
        `😔 *"${query}"* සඳහා results හමු නොවුණා.\nවෙනත් title try කරන්න.`,
        { chat_id: chatId, message_id: statusMsg.message_id, parse_mode: 'Markdown' }
      );
      return;
    }

    userState[chatId] = { results: all };

    const keyboard = all.slice(0, 8).map((r, i) => {
      const src  = r._src === 'cine' ? '🎞️' : '📦';
      const name = (r.title || '').replace(/ Sinhala Subtitles.*$/i, '').trim();
      const yr   = r.year ? ` (${r.year})` : '';
      return [{ text: `${src} ${name}${yr}`, callback_data: `pick_${i}` }];
    });

    await bot.editMessageText(
      `✅ *${all.length}* result(s) — select a movie:\n\n🎞️ CineVibes  📦 LKSubs`,
      {
        chat_id: chatId,
        message_id: statusMsg.message_id,
        parse_mode: 'Markdown',
        reply_markup: { inline_keyboard: keyboard }
      }
    );

  } catch (err) {
    console.error(err);
    await bot.editMessageText(`❌ Error: ${err.message}`, { chat_id: chatId, message_id: statusMsg.message_id });
  }
});

// ═══════════════════════════════════════
// CALLBACK
// ═══════════════════════════════════════
bot.on('callback_query', async (cb) => {
  const chatId = cb.message.chat.id;
  const msgId  = cb.message.message_id;
  const data   = cb.data;
  await bot.answerCallbackQuery(cb.id);

  // ── Movie selected ──
  if (data.startsWith('pick_')) {
    const idx = parseInt(data.replace('pick_', ''));
    const state = userState[chatId];
    if (!state?.results[idx]) return;

    const item = state.results[idx];
    await bot.editMessageText(`⏳ Loading details...`, { chat_id: chatId, message_id: msgId });

    try {
      let detail;
      if (item._src === 'cine') {
        detail = await cineDetail(item.link);
        if (detail) detail._src = 'cine';
      } else {
        detail = await lksubDetail(item.link);
        if (detail) detail._src = 'lksub';
      }
      if (!detail) throw new Error('Details load failed');

      userState[chatId].detail = detail;
      userState[chatId].itemLink = item.link;

      const title  = (detail.title || item.title || '').replace(/ Sinhala Subtitles.*$/i, '').trim();
      const genres = Array.isArray(detail.genres) ? detail.genres.join(', ') : (detail.genres || 'N/A');
      const imdb   = detail.imdb || 'N/A';
      const dur    = detail.duration ? `⏱️ *Duration:* ${detail.duration}\n` : '';
      const qual   = detail.quality  ? `📺 *Quality:* ${detail.quality}\n`   : '';
      const subBy  = detail.subtitle_by ? `\n✍️ *Subtitle by:* ${detail.subtitle_by}` : '';

      // Build download buttons
      const dlBtns = [];

      if (item._src === 'cine') {
        // SRT subtitle
        if (detail.subtitles?.length) {
          detail.subtitles.forEach((s, i) => {
            dlBtns.push([{ text: `📄 ${s.language} Subtitle (.srt) — Download`, callback_data: `srt_${i}` }]);
          });
        }
        // Movie downloads
        if (detail.downloads?.length) {
          detail.downloads
            .filter(d => !d.quality?.toLowerCase().includes('subtitle'))
            .forEach((d, i) => {
              dlBtns.push([{ text: `🎬 ${d.title} [${d.size}]`, callback_data: `mov_${i}` }]);
            });
        }
        dlBtns.push([{ text: '🌐 CineVibes ලෙස බලන්න', url: item.link }]);
      } else {
        // LKSubs ZIPs
        (detail.downloads || []).forEach((d, i) => {
          const isZip = d.link?.includes('.zip') || d.name?.toLowerCase().includes('subtitle');
          dlBtns.push([{
            text: isZip ? `📥 Subtitle ZIP — Download` : `🎬 ${d.name}`,
            callback_data: isZip ? `zip_${i}` : `ext_${i}`
          }]);
        });
        dlBtns.push([{ text: '🌐 LKSubs ලෙස බලන්න', url: item.link }]);
      }

      const caption =
`🎬 *${title}*
🎭 *Genres:* ${genres}
⭐ *IMDb:* ${imdb}
${dur}${qual}🗣️ *Subtitles:* Sinhala${subBy}

📥 *Download Options:*`;

      await bot.deleteMessage(chatId, msgId).catch(() => {});
      const img = detail.image || item.image;
      if (img) {
        await bot.sendPhoto(chatId, img, {
          caption, parse_mode: 'Markdown',
          reply_markup: { inline_keyboard: dlBtns }
        });
      } else {
        await bot.sendMessage(chatId, caption, {
          parse_mode: 'Markdown',
          reply_markup: { inline_keyboard: dlBtns }
        });
      }

    } catch (err) {
      console.error(err);
      await bot.sendMessage(chatId, `❌ Error: ${err.message}\n\n🔗 ${item.link}`);
    }
  }

  // ── SRT Download ──
  if (data.startsWith('srt_')) {
    const i = parseInt(data.replace('srt_', ''));
    const detail = userState[chatId]?.detail;
    if (!detail?.subtitles?.[i]) return;
    const sub = detail.subtitles[i];
    await sendFile(chatId, sub.link, '.srt', `📄 *${detail.title} — Sinhala Subtitle (.srt)*`);
  }

  // ── Movie download (CineVibes) — send link (too large for bot) ──
  if (data.startsWith('mov_')) {
    const i = parseInt(data.replace('mov_', ''));
    const detail = userState[chatId]?.detail;
    if (!detail?.downloads?.[i]) return;
    const dl = detail.downloads[i];
    await bot.sendMessage(chatId,
      `🎬 *${dl.title}* [${dl.size}]\n\n🔗 [Download Link](${dl.link})`,
      { parse_mode: 'Markdown', disable_web_page_preview: true }
    );
  }

  // ── LKSubs ZIP Download ──
  if (data.startsWith('zip_')) {
    const i = parseInt(data.replace('zip_', ''));
    const detail = userState[chatId]?.detail;
    if (!detail?.downloads?.[i]) return;
    const dl = detail.downloads[i];
    await sendFile(chatId, dl.link, '.zip', `📥 *Sinhala Subtitle ZIP*\n${dl.name || ''}`);
  }

  // ── External link (LKSubs movie file) ──
  if (data.startsWith('ext_')) {
    const i = parseInt(data.replace('ext_', ''));
    const detail = userState[chatId]?.detail;
    if (!detail?.downloads?.[i]) return;
    const dl = detail.downloads[i];
    await bot.sendMessage(chatId,
      `🎬 *${dl.name}*\n\n🔗 [Download Link](${dl.link})`,
      { parse_mode: 'Markdown', disable_web_page_preview: true }
    );
  }
});

// ═══════════════════════════════════════
// SEND FILE HELPER
// ═══════════════════════════════════════
async function sendFile(chatId, url, ext, caption) {
  const statusMsg = await bot.sendMessage(chatId, `⏳ Downloading... please wait`);
  try {
    const filePath = await downloadFile(url, ext);
    const sizeMB = (fs.statSync(filePath).size / 1024 / 1024).toFixed(2);
    await bot.editMessageText(`📦 Sending (${sizeMB} MB)...`, {
      chat_id: chatId, message_id: statusMsg.message_id
    });
    await bot.sendDocument(chatId, filePath, { caption, parse_mode: 'Markdown' });
    fs.unlinkSync(filePath);
    await bot.deleteMessage(chatId, statusMsg.message_id).catch(() => {});
  } catch (err) {
    console.error('File send error:', err.message);
    // Fallback — send direct link so user can download manually
    await bot.editMessageText(
      `⚠️ Bot direct download failed.\n\n📎 *Manual download link:*\n[Click here to download](${url})\n\n_(Browser ලෙස open කරලා download කරන්න)_`,
      {
        chat_id: chatId,
        message_id: statusMsg.message_id,
        parse_mode: 'Markdown',
        disable_web_page_preview: true
      }
    );
  }
}

bot.on('polling_error', (err) => console.error('Polling error:', err.message));
