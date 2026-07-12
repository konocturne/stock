const fs = require('fs');
const JSDOM = require('jsdom').JSDOM;
const dom = new JSDOM(fs.readFileSync('dashboard/index.html', 'utf8'));
global.document = dom.window.document;
global.window = dom.window;

// stub fetch
global.fetch = async (url) => {
  return {
    ok: true,
    json: async () => JSON.parse(fs.readFileSync('dashboard/data.json', 'utf8'))
  };
};
global.Chart = class { constructor() {} };

// load app.js
require('./dashboard/app.js');

// simulate DOMContentLoaded
dom.window.document.dispatchEvent(new dom.window.Event('DOMContentLoaded'));

setTimeout(() => {
  if (document.getElementById('loading').style.display === 'none' && document.getElementById('error-screen').style.display === 'none') {
    console.log("SUCCESS");
  } else if (document.getElementById('error-screen').style.display !== 'none') {
    console.log("ERROR SCREEN SHOWN");
  } else {
    console.log("STUCK ON LOADING");
  }
}, 500);
