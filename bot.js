const TelegramBot = require('node-telegram-bot-api');

const TOKEN      = process.env.BOT_TOKEN;
const ADMIN_IDS  = (process.env.ADMIN_IDS || '').split(',').map(s => s.trim()).filter(Boolean);
const CHANNEL_ID = process.env.TG_CHANNEL || '@Hitestpost';
const TMDB_TOKEN = process.env.TMDB_TOKEN || 'eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiI2Mjk3MGIwMjJhMGNmZDM0ZDlhZmEyOGMxMzFiZTk3YiIsIm5iZiI6MTc3OTI5MzQ1Mi4yOTIsInN1YiI6IjZhMGRkZDBjZWYyNGZkN2Y4YmRmNTNmZSIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.aSygYNT53J7Il2b0Z6S52nDADRexnLfSy2x2pNbhs4c';
const TMDB_API   = process.env.TMDB_API_KEY || '62970b022a0cfd34d9afa28c131be97b';

if (!TOKEN) { console.error('❌ BOT_TOKEN not set'); process.exit(1); }

const bot = new TelegramBot(TOKEN, { polling: true });
console.log('🌸 VIMA Post Bot started!');

const userState = {};

// ══════════════════════════════════════════
// ADMIN CHECK
// ══════════════════════════════════════════
function isAdmin(userId) {
  if (!ADMIN_IDS.length) return true; // no restriction if not set
  return ADMIN_IDS.includes(String(userId));
}

// ══════════════════════════════════════════
// TMDB API
// ══════════════════════════════════════════
async function tmdbSearch(query) {
  const r = await fetch(`https://api.themoviedb.org/3/search/multi?query=${encodeURIComponent(query)}&include_adult=false&language=en-US&page=1`, {
    headers: { 'Authorization': `Bearer ${TMDB_TOKEN}`, 'accept': 'application/json' }
  });
  const d = await r.json();
  return (d.results || []).filter(x => x.media_type !== 'person').slice(0, 8);
}

async function tmdbDetail(id, type) {
  const url = `https://api.themoviedb.org/3/${type}/${id}?append_to_response=credits&language=en-US`;
  const r = await fetch(url, {
    headers: { 'Authorization': `Bearer ${TMDB_TOKEN}`, 'accept': 'application/json' }
  });
  return r.json();
}

// ══════════════════════════════════════════
// BUILD POST
// ══════════════════════════════════════════
function buildPost(detail, type, extra = {}) {
  const isTV    = type === 'tv';
  const title   = detail.title || detail.name || '';
  const year    = (detail.release_date || detail.first_air_date || '').slice(0, 4);
  const rating  = detail.vote_average ? detail.vote_average.toFixed(1) : 'N/A';
  const genres  = (detail.genres || []).slice(0, 3).map(g => g.name).join(' • ');
  const runtime = detail.runtime ? `${detail.runtime} min` : (detail.episode_run_time?.[0] ? `${detail.episode_run_time[0]} min/ep` : '');
  const lang    = detail.original_language?.toUpperCase() || '';
  const country = (detail.production_countries || [])[0]?.iso_3166_1 || '';
  const cast    = (detail.credits?.cast || []).slice(0, 5).map(c => c.name).join(', ') || 'N/A';
  const overview = (detail.overview || '').slice(0, 280);
  const seasons  = detail.number_of_seasons ? `${detail.number_of_seasons} Seasons` : '';
  const episodes = detail.number_of_episodes ? `${detail.number_of_episodes} Episodes` : '';

  const typeIcon = isTV ? '📺' : '🎬';
  const typeLabel = isTV ? 'TV SERIES' : 'MOVIE';

  const qualityLine = extra.quality ? `\n🎞 *Quality :* ${extra.quality}` : '';
  const subLine     = extra.sub     ? `\n📝 *Subtitles :* ${extra.sub}`   : '\n📝 *Subtitles :* සිංහල උපසිරැසි සමග';

  return `${typeIcon} *${title}* ${year ? `(${year})` : ''}
━━━━━━━━━━━━━━━━━━━━━
🏷 *Type :* ${typeLabel}
⭐ *IMDb :* ${rating}/10
🎭 *Genre :* ${genres}
🌍 *Country :* ${country} | ${lang}
${runtime ? `⏱ *Runtime :* ${runtime}\n` : ''}${seasons ? `📅 *Seasons :* ${seasons} | ${episodes}\n` : ''}👥 *Cast :* ${cast}${qualityLine}${subLine}
━━━━━━━━━━━━━━━━━━━━━
📖 ${overview}${overview.length >= 280 ? '...' : ''}
━━━━━━━━━━━━━━━━━━━━━
🎬 *Movie Mania LK*`;
}

function buildButtons(detail, type) {
  const title = detail.title || detail.name || '';
  const year  = (detail.release_date || detail.first_air_date || '').slice(0, 4);
  const slug  = title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
  const siteUrl = `https://moviemanialk.com/${type === 'tv' ? 'tv' : 'movie'}/${slug}${year ? '-' + year : ''}`;

  return {
    inline_keyboard: [
      [{ text: '🎬 Download Now', url: siteUrl }],
      [
        { text: '💬 WhatsApp Channel', url: 'https://whatsapp.com/channel/0029Vb6dIi242DccwGQfTr2R' },
        { text: '👍 Facebook Page',    url: 'https://www.facebook.com/profile.php?id=61578959931824' }
      ]
    ]
  };
}

// ══════════════════════════════════════════
// /start
// ══════════════════════════════════════════
bot.onText(/\/start/, async (msg) => {
  const chatId = msg.chat.id;
  const name   = msg.from.first_name || 'යාළුවා';
  const admin  = isAdmin(msg.from.id);

  try {
    await bot.sendPhoto(chatId,
      'https://i.ibb.co/ynN2TZSH/0000000069f481f4920da79c28607b62.jpg'
    ).catch(() => {});
  } catch(e) {}

  bot.sendMessage(chatId,
`🌸 *VIMA SUBTITLES BOT*
━━━━━━━━━━━━━━━━
👋 හෙලෝ *${name}*!
${admin ? '\n🔑 *Admin Mode Active*' : ''}

${admin ? `*📢 POST TO CHANNEL:*
/post — Movie search කරලා channel ලෙස post

` : ''}*Commands:*
/start — Bot start
/id — Chat ID`,
    { parse_mode: 'Markdown',
      reply_markup: admin ? {
        keyboard: [[{ text: '🎬 New Post' }], [{ text: '🆔 My ID' }]],
        resize_keyboard: true
      } : { remove_keyboard: true }
    }
  );
});

bot.onText(/\/id/, (msg) => {
  bot.sendMessage(msg.chat.id, `🆔 Your ID: \`${msg.from.id}\``, { parse_mode: 'Markdown' });
});

// ══════════════════════════════════════════
// POST FLOW
// ══════════════════════════════════════════
bot.onText(/\/post|🎬 New Post/, async (msg) => {
  if (!isAdmin(msg.from.id)) return;
  const chatId = msg.chat.id;
  userState[chatId] = { step: 'search' };
  bot.sendMessage(chatId,
    `🔍 *Movie / Series name ලියන්න:*`,
    { parse_mode: 'Markdown', reply_markup: { force_reply: true } }
  );
});

// ══════════════════════════════════════════
// MESSAGE HANDLER
// ══════════════════════════════════════════
bot.on('message', async (msg) => {
  if (!msg.text || msg.text.startsWith('/')) return;
  const chatId = msg.chat.id;
  const state  = userState[chatId];
  const text   = msg.text.trim();

  // 🎬 New Post button
  if (text === '🎬 New Post') {
    if (!isAdmin(msg.from.id)) return;
    userState[chatId] = { step: 'search' };
    return bot.sendMessage(chatId, `🔍 *Movie / Series name ලියන්න:*`, { parse_mode: 'Markdown' });
  }
  if (text === '🆔 My ID') {
    return bot.sendMessage(chatId, `🆔 Your ID: \`${msg.from.id}\``, { parse_mode: 'Markdown' });
  }

  if (!state) return;

  // ── Step: Search ──
  if (state.step === 'search') {
    if (!isAdmin(msg.from.id)) return;
    const st = await bot.sendMessage(chatId, `🔍 Searching *"${text}"*...`, { parse_mode: 'Markdown' });
    try {
      const results = await tmdbSearch(text);
      if (!results.length) {
        return bot.editMessageText(`😔 No results for *"${text}"*`, {
          chat_id: chatId, message_id: st.message_id, parse_mode: 'Markdown'
        });
      }
      userState[chatId] = { step: 'pick', results };

      const lines = results.map((r, i) => {
        const t    = r.title || r.name;
        const yr   = (r.release_date || r.first_air_date || '').slice(0, 4);
        const type = r.media_type === 'tv' ? '📺' : '🎬';
        const rat  = r.vote_average ? ` ⭐${r.vote_average.toFixed(1)}` : '';
        return `${i + 1}. ${type} *${t}*${yr ? ` (${yr})` : ''}${rat}`;
      }).join('\n');

      const nums = results.map((_, i) => ({ text: `${i + 1}`, callback_data: `tmdb_${i}` }));
      const rows = [];
      for (let i = 0; i < nums.length; i += 4) rows.push(nums.slice(i, i + 4));
      rows.push([{ text: '❌ Cancel', callback_data: 'cancel' }]);

      bot.editMessageText(
        `✅ *Results:*\n━━━━━━━━━━━━━━━━\n${lines}\n━━━━━━━━━━━━━━━━\n🎯 *Select* 👇`,
        { chat_id: chatId, message_id: st.message_id, parse_mode: 'Markdown',
          reply_markup: { inline_keyboard: rows } }
      );
    } catch(e) {
      bot.editMessageText(`❌ Error: ${e.message}`, { chat_id: chatId, message_id: st.message_id });
    }
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

  if (!isAdmin(cb.from.id)) return;

  // Cancel
  if (data === 'cancel') {
    delete userState[chatId];
    return bot.editMessageText('❌ Cancelled.', { chat_id: chatId, message_id: msgId });
  }

  // ── Pick TMDB result ──
  if (data.startsWith('tmdb_')) {
    const idx    = parseInt(data.replace('tmdb_', ''));
    const state  = userState[chatId];
    if (!state?.results?.[idx]) return;
    const item   = state.results[idx];
    const type   = item.media_type;

    await bot.editMessageText('⏳ Loading details...', { chat_id: chatId, message_id: msgId });

    try {
      const detail = await tmdbDetail(item.id, type);
      userState[chatId] = { step: 'preview', detail, type };

      const caption  = buildPost(detail, type);
      const poster   = detail.poster_path ? `https://image.tmdb.org/t/p/w500${detail.poster_path}` : null;
      const btns     = buildButtons(detail, type);

      // Add confirm/edit buttons
      const confirmBtns = {
        inline_keyboard: [
          [{ text: '📢 Post to Channel ✅', callback_data: 'confirm_post' }],
          [
            { text: '✏️ Edit Quality', callback_data: 'edit_quality' },
            { text: '📝 Edit Subtitle', callback_data: 'edit_sub' }
          ],
          [{ text: '❌ Cancel', callback_data: 'cancel' }]
        ]
      };

      await bot.deleteMessage(chatId, msgId).catch(() => {});

      if (poster) {
        await bot.sendPhoto(chatId, poster, {
          caption: `*PREVIEW:*\n━━━━━━━━━━━━━━━━\n${caption}`.slice(0, 1024),
          parse_mode: 'Markdown',
          reply_markup: confirmBtns
        });
      } else {
        await bot.sendMessage(chatId, `*PREVIEW:*\n━━━━━━━━━━━━━━━━\n${caption}`, {
          parse_mode: 'Markdown',
          reply_markup: confirmBtns
        });
      }
    } catch(e) {
      bot.sendMessage(chatId, `❌ Error: ${e.message}`);
    }
  }

  // ── Confirm Post ──
  if (data === 'confirm_post') {
    const state = userState[chatId];
    if (!state?.detail) return;
    const { detail, type } = state;

    await bot.editMessageReplyMarkup({ inline_keyboard: [] }, { chat_id: chatId, message_id: msgId }).catch(() => {});

    const caption = buildPost(detail, type, state.extra || {});
    const poster  = detail.poster_path ? `https://image.tmdb.org/t/p/original${detail.poster_path}` : null;
    const btns    = buildButtons(detail, type);

    let channelMsg;
    try {
      if (poster) {
        channelMsg = await bot.sendPhoto(CHANNEL_ID, poster, {
          caption: caption.slice(0, 1024),
          parse_mode: 'Markdown',
          reply_markup: btns
        });
      } else {
        channelMsg = await bot.sendMessage(CHANNEL_ID, caption, {
          parse_mode: 'Markdown',
          reply_markup: btns
        });
      }

      await bot.sendMessage(chatId,
        `✅ *Posted to channel!*\n\n[View Post](https://t.me/${CHANNEL_ID.replace('@', '')}/${channelMsg.message_id})`,
        { parse_mode: 'Markdown' }
      );
      delete userState[chatId];
    } catch(e) {
      bot.sendMessage(chatId, `❌ Post failed: ${e.message}`);
    }
  }

  // ── Edit Quality ──
  if (data === 'edit_quality') {
    const qBtns = {
      inline_keyboard: [
        [
          { text: '4K UHD', callback_data: 'q_4K UHD' },
          { text: '1080p FHD', callback_data: 'q_1080p FHD' }
        ],
        [
          { text: '720p HD', callback_data: 'q_720p HD' },
          { text: '480p', callback_data: 'q_480p' }
        ],
        [{ text: '🔙 Back', callback_data: 'back_preview' }]
      ]
    };
    bot.editMessageReplyMarkup(qBtns, { chat_id: chatId, message_id: msgId });
  }

  if (data.startsWith('q_')) {
    const quality = data.replace('q_', '');
    if (!userState[chatId]) return;
    userState[chatId].extra = { ...(userState[chatId].extra || {}), quality };
    const state = userState[chatId];
    const caption = buildPost(state.detail, state.type, state.extra);
    bot.editMessageCaption
      ? bot.editMessageCaption(`*PREVIEW:*\n━━━━━━━━━━━━━━━━\n${caption}`.slice(0,1024), {
          chat_id: chatId, message_id: msgId, parse_mode: 'Markdown',
          reply_markup: {
            inline_keyboard: [
              [{ text: '📢 Post to Channel ✅', callback_data: 'confirm_post' }],
              [{ text: '✏️ Edit Quality', callback_data: 'edit_quality' }, { text: '📝 Edit Subtitle', callback_data: 'edit_sub' }],
              [{ text: '❌ Cancel', callback_data: 'cancel' }]
            ]
          }
        })
      : bot.editMessageText(`*PREVIEW:*\n━━━━━━━━━━━━━━━━\n${caption}`, {
          chat_id: chatId, message_id: msgId, parse_mode: 'Markdown',
          reply_markup: {
            inline_keyboard: [
              [{ text: '📢 Post to Channel ✅', callback_data: 'confirm_post' }],
              [{ text: '✏️ Edit Quality', callback_data: 'edit_quality' }, { text: '📝 Edit Subtitle', callback_data: 'edit_sub' }],
              [{ text: '❌ Cancel', callback_data: 'cancel' }]
            ]
          }
        });
  }

  // ── Edit Subtitle ──
  if (data === 'edit_sub') {
    const sBtns = {
      inline_keyboard: [
        [{ text: '🇱🇰 සිංහල උපසිරැසි සමග', callback_data: 's_සිංහල උපසිරැසි සමග' }],
        [{ text: '🇬🇧 English Subtitles', callback_data: 's_English Subtitles' }],
        [{ text: '🌐 Multi Subtitles', callback_data: 's_Multi Subtitles' }],
        [{ text: '🔙 Back', callback_data: 'back_preview' }]
      ]
    };
    bot.editMessageReplyMarkup(sBtns, { chat_id: chatId, message_id: msgId });
  }

  if (data.startsWith('s_')) {
    const sub = data.replace('s_', '');
    if (!userState[chatId]) return;
    userState[chatId].extra = { ...(userState[chatId].extra || {}), sub };
    bot.editMessageReplyMarkup({
      inline_keyboard: [
        [{ text: '📢 Post to Channel ✅', callback_data: 'confirm_post' }],
        [{ text: '✏️ Edit Quality', callback_data: 'edit_quality' }, { text: '📝 Edit Subtitle', callback_data: 'edit_sub' }],
        [{ text: '❌ Cancel', callback_data: 'cancel' }]
      ]
    }, { chat_id: chatId, message_id: msgId });
  }

  // Back to preview buttons
  if (data === 'back_preview') {
    bot.editMessageReplyMarkup({
      inline_keyboard: [
        [{ text: '📢 Post to Channel ✅', callback_data: 'confirm_post' }],
        [{ text: '✏️ Edit Quality', callback_data: 'edit_quality' }, { text: '📝 Edit Subtitle', callback_data: 'edit_sub' }],
        [{ text: '❌ Cancel', callback_data: 'cancel' }]
      ]
    }, { chat_id: chatId, message_id: msgId });
  }
});

bot.on('polling_error', e => console.error('Polling:', e.message));
