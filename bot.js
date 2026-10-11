const TelegramBot = require('node-telegram-bot-api');
const https = require('https');
const http = require('http');
const fs = require('fs');
const path = require('path');
const os = require('os');

const TOKEN = process.env.BOT_TOKEN;
if (!TOKEN) { console.error('BOT_TOKEN not set!'); process.exit(1); }

const API_KEY = 'chama_api_584829ed7f1b24120633e2c272f9b98d';
const BASE    = 'https://api.chamindu.site/api/v1';

const bot = new TelegramBot(TOKEN, { polling: true });
console.log('🌸 VIMA SUBTITLES BOT started...');

const BANNER = 'https://ibb.co/ynN2TZSH'; // will use user's image
const userState = {};

// ══════════════════════════════════════════
// API SOURCES
// ══════════════════════════════════════════
const SOURCES = {
  lksub:    { name: '📦 LKSubs',    search: q => `${BASE}/movies/lksub/search?q=${enc(q)}&api_key=${API_KEY}`,    detail: u => `${BASE}/movies/lksub/infodl?q=${enc(u)}&api_key=${API_KEY}` },
  piratelk: { name: '🏴 PirateLK',  search: q => `${BASE}/movies/piratelk/search?q=${enc(q)}&api_key=${API_KEY}`, detail: u => `${BASE}/movies/piratelk/infodl?q=${enc(u)}&api_key=${API_KEY}` },
  zoom:     { name: '🎬 Zoom.lk',   search: q => `${BASE}/zoom/search?q=${enc(q)}&api_key=${API_KEY}`,            detail: u => `${BASE}/zoom/infodl?q=${enc(u)}&api_key=${API_KEY}` },
  cinemx:   { name: '🎞️ CineMX',   search: q => `${BASE}/movies/cinemx/search?q=${enc(q)}&api_key=${API_KEY}`,   detail: u => `${BASE}/movies/cinemx/infodl?q=${enc(u)}&api_key=${API_KEY}` },
};

const enc = s => encodeURIComponent(s);

async function apiGet(url) {
  const r = await fetch(url);
  return r.json();
}

async function searchAll(q) {
  const results = [];
  const jobs = Object.entries(SOURCES).map(async ([key, src]) => {
    try {
      const d = await apiGet(src.search(q));
      if (d.status && d.data?.length) {
        d.data.slice(0,5).forEach(item => results.push({ ...item, _src: key, _srcName: src.name }));
      }
    } catch(e) { console.error(key, e.message); }
  });
  await Promise.allSettled(jobs);
  return results;
}

async function getDetail(src, link) {
  const d = await apiGet(SOURCES[src].detail(link));
  return d.status ? { ...(d.data||{}), _src: src } : null;
}

// ══════════════════════════════════════════
// FILE DOWNLOAD HELPER
// ══════════════════════════════════════════
function downloadFile(url, ext) {
  return new Promise((resolve, reject) => {
    const tmp = path.join(os.tmpdir(), 'vima_' + Date.now() + (ext||'.bin'));
    const file = fs.createWriteStream(tmp);
    function doGet(u, hops=0) {
      if (hops > 5) return reject(new Error('Too many redirects'));
      const proto = u.startsWith('https') ? https : http;
      proto.get(u, { headers: { 'User-Agent': 'Mozilla/5.0', 'Referer': 'https://lksubs.com/' } }, res => {
        if ([301,302,307,308].includes(res.statusCode) && res.headers.location)
          return doGet(res.headers.location, hops+1);
        if (res.statusCode !== 200) return reject(new Error('HTTP ' + res.statusCode));
        res.pipe(file);
        file.on('finish', () => { file.close(); resolve(tmp); });
        file.on('error', reject);
      }).on('error', reject);
    }
    doGet(url);
  });
}

// ══════════════════════════════════════════
// CLEAN TITLE
// ══════════════════════════════════════════
function cleanTitle(t='') {
  return t.replace(/ (With |)\bSinhala\b.*/i,'').replace(/\[.*?\]/g,'').replace(/\(සිංහල.*?\)/g,'').trim();
}

// ══════════════════════════════════════════
// /start
// ══════════════════════════════════════════
bot.onText(/\/start/, async (msg) => {
  const name = msg.from.first_name || 'යාළුවා';
  const chatId = msg.chat.id;

  await bot.sendMessage(chatId,
`🌸 *VIMA SUBTITLES BOT* 🌸
━━━━━━━━━━━━━━━━
👋 හෙලෝ *${name}*!

✨ SEND ANY MOVIE NAME
🔍 I WILL SEARCH SUBTITLES

📌 *EXAMPLES:*
• Deadpool
• Enola Holmes
• Breaking Bad

👇 JUST SEND THE NAME
━━━━━━━━━━━━━━━━
_CREATE BY GAVESH VIMANSHANA_`,
    {
      parse_mode: 'Markdown',
      reply_markup: {
        keyboard: [
          ['📚 HELP', 'ℹ️ ABOUT'],
          ['🟢 ALIVE', '🎯 SUB ONLY'],
        ],
        resize_keyboard: true
      }
    }
  );
});

// ══════════════════════════════════════════
// KEYBOARD COMMANDS
// ══════════════════════════════════════════
bot.onText(/📚 HELP|\/help/, (msg) => {
  bot.sendMessage(msg.chat.id,
`📚 *HELP*
━━━━━━━━━━━━━━━━
🔍 Movie name type කරලා send කරන්න

📦 *Sources:*
📦 LKSubs — Subtitle ZIPs
🏴 PirateLK — Subtitles
🎬 Zoom.lk — TV + Movies
🎞️ CineMX — HD Movies

📥 Result select කරලා download link ගන්න
━━━━━━━━━━━━━━━━
_CREATE BY GAVESH VIMANSHANA_`,
    { parse_mode: 'Markdown' }
  );
});

bot.onText(/ℹ️ ABOUT|\/about/, (msg) => {
  bot.sendMessage(msg.chat.id,
`ℹ️ *ABOUT*
━━━━━━━━━━━━━━━━
🌸 *VIMA SUBTITLES BOT*

🤖 Sinhala Subtitle search bot
📦 Sources: LKSubs, PirateLK, Zoom, CineMX
👨‍💻 Creator: Gavesh Vimanshana
━━━━━━━━━━━━━━━━`,
    { parse_mode: 'Markdown' }
  );
});

bot.onText(/🟢 ALIVE|\/alive/, (msg) => {
  bot.sendMessage(msg.chat.id, '🟢 *BOT IS ALIVE!*\n\nAll systems running ✅', { parse_mode: 'Markdown' });
});

bot.onText(/\/id/, (msg) => {
  bot.sendMessage(msg.chat.id, `🆔 Chat ID: \`${msg.chat.id}\``, { parse_mode: 'Markdown' });
});

// ══════════════════════════════════════════
// TEXT → SEARCH
// ══════════════════════════════════════════
bot.on('message', async (msg) => {
  if (!msg.text) return;
  const skip = ['/start','/help','/about','/alive','/id','📚 HELP','ℹ️ ABOUT','🟢 ALIVE','🎯 SUB ONLY'];
  if (skip.some(s => msg.text.startsWith(s))) return;
  if (msg.text.startsWith('/')) return;

  const chatId = msg.chat.id;
  const query  = msg.text.trim();

  const st = await bot.sendMessage(chatId,
`🔍 *SEARCHING...*
━━━━━━━━━━━━━━━━
🎬 *"${query}"*
⏳ Please wait...`,
    { parse_mode: 'Markdown' }
  );

  try {
    const results = await searchAll(query);

    if (!results.length) {
      return bot.editMessageText(
`😔 *NO RESULTS*
━━━━━━━━━━━━━━━━
❌ *"${query}"* — results නෑ
Try another title`,
        { chat_id: chatId, message_id: st.message_id, parse_mode: 'Markdown' }
      );
    }

    // Deduplicate by link
    const seen = new Set();
    const unique = results.filter(r => {
      if (seen.has(r.link)) return false;
      seen.add(r.link); return true;
    });

    userState[chatId] = { results: unique, query };

    // Build result text
    const lines = unique.slice(0,10).map((r,i) =>
      `${i+1}. ${r._srcName} ${cleanTitle(r.title)}${r.year&&r.year!=='N/A'?' ('+r.year+')':''}`
    ).join('\n');

    // Number buttons (like screenshot)
    const nums = unique.slice(0,10).map((_,i) => ({ text: `${i+1}`, callback_data: `pick_${i}` }));
    const rows = [];
    for (let i=0; i<nums.length; i+=5) rows.push(nums.slice(i,i+5));
    rows.push([{ text: '🔙 BACK', callback_data: 'back_search' }]);

    await bot.editMessageText(
`✨ *SEARCH RESULTS* ✨
━━━━━━━━━━━━━━━━
🎯 *SELECT* 👇

${lines}

━━━━━━━━━━━━━━━━
_CREATE BY GAVESH VIMANSHANA_`,
      {
        chat_id: chatId,
        message_id: st.message_id,
        parse_mode: 'Markdown',
        reply_markup: { inline_keyboard: rows }
      }
    );

  } catch(e) {
    console.error(e);
    bot.editMessageText(`❌ Error: ${e.message}`, { chat_id: chatId, message_id: st.message_id });
  }
});

// ══════════════════════════════════════════
// CALLBACKS
// ══════════════════════════════════════════
bot.on('callback_query', async (cb) => {
  const chatId = cb.message.chat.id;
  const msgId  = cb.message.message_id;
  const data   = cb.data;
  await bot.answerCallbackQuery(cb.id);

  // ── Back ──
  if (data === 'back_search') {
    const state = userState[chatId];
    if (!state) return;
    const unique = state.results;
    const lines = unique.slice(0,10).map((r,i) =>
      `${i+1}. ${r._srcName} ${cleanTitle(r.title)}${r.year&&r.year!=='N/A'?' ('+r.year+')':''}`
    ).join('\n');
    const nums = unique.slice(0,10).map((_,i) => ({ text: `${i+1}`, callback_data: `pick_${i}` }));
    const rows = [];
    for (let i=0; i<nums.length; i+=5) rows.push(nums.slice(i,i+5));
    rows.push([{ text: '🔙 BACK', callback_data: 'back_search' }]);
    return bot.editMessageText(
`✨ *SEARCH RESULTS* ✨
━━━━━━━━━━━━━━━━
🎯 *SELECT* 👇

${lines}

━━━━━━━━━━━━━━━━
_CREATE BY GAVESH VIMANSHANA_`,
      { chat_id: chatId, message_id: msgId, parse_mode: 'Markdown', reply_markup: { inline_keyboard: rows } }
    );
  }

  // ── Pick result ──
  if (data.startsWith('pick_')) {
    const idx  = parseInt(data.replace('pick_',''));
    const item = userState[chatId]?.results?.[idx];
    if (!item) return;

    await bot.editMessageText(
`⏳ *LOADING...*
━━━━━━━━━━━━━━━━
🔍 Getting details...`,
      { chat_id: chatId, message_id: msgId, parse_mode: 'Markdown' }
    );

    try {
      const detail = await getDetail(item._src, item.link);
      if (!detail) throw new Error('Details load failed');
      userState[chatId].detail = detail;
      userState[chatId].item   = item;

      const title   = cleanTitle(detail.title || item.title || '');
      const genres  = Array.isArray(detail.genres) ? detail.genres.join(', ') : (detail.genres||'N/A');
      const imdb    = detail.imdb || item.rating || 'N/A';
      const lang    = detail.language || 'Sinhala';
      const cast    = Array.isArray(detail.cast) ? detail.cast.slice(0,4).join(', ') : 'N/A';
      const dur     = detail.duration || '';
      const qual    = detail.quality  || '';
      const story   = (detail.story||'').replace(/\n/g,' ').slice(0,250);
      const dlCount = (detail.downloads||[]).length;

      // Download buttons
      const dlBtns = [];
      (detail.downloads||[]).forEach((d,i) => {
        const name = d.name||d.title||'Download';
        const isZip  = d.link?.includes('.zip');
        const isSub  = name.toLowerCase().includes('subtitle')||name.includes('SRT')||isZip;
        const isMov  = name.toLowerCase().includes('movie')||name.toLowerCase().includes('mp4')||name.toLowerCase().includes('mkv')||['4K','1080p','720p','480p'].some(q=>name.includes(q));
        const icon   = isZip ? '📥' : isSub ? '📝' : isMov ? '🎬' : '🔗';
        const size   = d.size && d.size!=='N/A' ? ` [${d.size}]` : '';
        dlBtns.push([{ text: `${icon} ${name.replace(/[📁🎥📝🎬]/g,'').trim()}${size}`.slice(0,60), callback_data: `dl_${i}` }]);
      });
      dlBtns.push([
        { text: '🌐 Open Site', url: item.link },
        { text: '🔙 BACK', callback_data: 'back_search' }
      ]);

      const infoText =
`${item._srcName} *${title}*
━━━━━━━━━━━━━━━━
⭐ *RATING :* ${imdb}
🌐 *LANGUAGE :* ${lang.toUpperCase()}
🎭 *GENRE :* ${genres}
👥 *CAST :* ${cast}
${dur ? `⏱️ *DURATION :* ${dur}\n` : ''}${qual ? `📺 *QUALITY :* ${qual}\n` : ''}📥 *SUBTITLES :* ${dlCount}
━━━━━━━━━━━━━━━━
${story ? `📖 ${story}...\n━━━━━━━━━━━━━━━━\n` : ''}📥 *DOWNLOAD OPTIONS* 👇
_CREATE BY GAVESH VIMANSHANA_`;

      await bot.deleteMessage(chatId, msgId).catch(()=>{});

      const img = detail.image || item.image;
      if (img && !img.includes('placeholder')) {
        await bot.sendPhoto(chatId, img, {
          caption: infoText.slice(0,1024),
          parse_mode: 'Markdown',
          reply_markup: { inline_keyboard: dlBtns }
        }).catch(async () => {
          await bot.sendMessage(chatId, infoText, {
            parse_mode: 'Markdown',
            reply_markup: { inline_keyboard: dlBtns }
          });
        });
      } else {
        await bot.sendMessage(chatId, infoText, {
          parse_mode: 'Markdown',
          reply_markup: { inline_keyboard: dlBtns }
        });
      }

    } catch(e) {
      console.error(e);
      bot.sendMessage(chatId,
`❌ *ERROR*
━━━━━━━━━━━━━━━━
${e.message}

🔗 [Open Manually](${item.link})`,
        { parse_mode: 'Markdown', reply_markup: { inline_keyboard: [[{ text:'🔙 BACK', callback_data:'back_search' }]] } }
      );
    }
  }

  // ── Download ──
  if (data.startsWith('dl_')) {
    const i      = parseInt(data.replace('dl_',''));
    const detail = userState[chatId]?.detail;
    const item   = userState[chatId]?.item;
    if (!detail) return;

    const dl   = detail.downloads?.[i];
    if (!dl) return;

    const name   = dl.name||dl.title||'Download';
    const link   = dl.link;
    const isZip  = link?.includes('.zip');
    const isSrt  = link?.includes('.srt');

    // Try to send small files (ZIP/SRT) directly
    if (isZip || isSrt) {
      const ext  = isZip ? '.zip' : '.srt';
      const stMsg = await bot.sendMessage(chatId,
`⏳ *DOWNLOADING...*
━━━━━━━━━━━━━━━━
📥 ${name}`,
        { parse_mode: 'Markdown' }
      );
      try {
        const fp = await downloadFile(link, ext);
        const mb = (fs.statSync(fp).size/1024/1024).toFixed(2);
        await bot.editMessageText(`📦 *SENDING (${mb} MB)...*`, {
          chat_id: chatId, message_id: stMsg.message_id, parse_mode: 'Markdown'
        });
        await bot.sendDocument(chatId, fp, {
          caption: `📥 *${name}*\n\n_CREATE BY GAVESH VIMANSHANA_`,
          parse_mode: 'Markdown'
        });
        fs.unlinkSync(fp);
        bot.deleteMessage(chatId, stMsg.message_id).catch(()=>{});
      } catch(e) {
        console.error('DL error:', e.message);
        // Fallback to link button
        bot.editMessageText(
`⚠️ *DIRECT DOWNLOAD FAILED*
━━━━━━━━━━━━━━━━
🔗 *DOWNLOAD LINK:*
${link}

💡 ඉහත link එක browser ලෙකෙන් open කරන්න.
━━━━━━━━━━━━━━━━
_CREATE BY GAVESH VIMANSHANA_`,
          {
            chat_id: chatId,
            message_id: stMsg.message_id,
            parse_mode: 'Markdown',
            reply_markup: { inline_keyboard: [[{ text: '🔗 DOWNLOAD LINK', url: link }],[{ text:'🔙 BACK', callback_data:'back_search' }]] }
          }
        );
      }
    } else {
      // Movie files / external links — send as button
      const size = dl.size && dl.size!=='N/A' ? `\n📦 Size: ${dl.size}` : '';
      bot.sendMessage(chatId,
`🎬 *${name}*${size}
━━━━━━━━━━━━━━━━
_CREATE BY GAVESH VIMANSHANA_`,
        {
          parse_mode: 'Markdown',
          reply_markup: { inline_keyboard: [
            [{ text: '🔗 DOWNLOAD LINK', url: link }],
            [{ text: '🔙 BACK', callback_data: 'back_search' }]
          ]}
        }
      );
    }
  }
});

bot.on('polling_error', e => console.error('Polling:', e.message));
