require('./bot.js');
process.on('uncaughtException', e => console.error('[Uncaught]', e.message));
process.on('unhandledRejection', e => console.error('[Unhandled]', e));
