// ==================== KONFIGURASI ====================
const CONFIG = {
  // ===== API CONFIG =====
  API_URL: 'https://vivid-sydelle-jamaa-c03b69c9.koyeb.app',
  API_KEY: 'kunci975635885rii7',
  GAME_NAME: 'susunkata',
  
  // ===== SHEET CONFIG (PILIH SALAH SATU) =====
  
  // Opsi 1: Pakai Sheet ID (REKOMENDASI)
  SHEET_ID: '14yci2PN7PzwmTG-x-hN2Ek3laiBmrA0iiav2EBFEO1U',
  SHEET_NAME: 'Leaderboard',
  
  // Opsi 2: Pakai Sheet aktif (comment salah satu)
  // SHEET_NAME: 'Leaderboard', // Akan pakai spreadsheet yang sedang dibuka
  
  // ===== KOLOM DATA =====
  START_ROW: 2,        // Baris pertama data (setelah header)
  COL_USER_ID: 1,      // Kolom A
  COL_NAMA: 2,         // Kolom B
  COL_POIN: 3,         // Kolom C
};

// ==================== FUNGSI UTAMA ====================
function importData() {
  const startTime = new Date().getTime();
  
  try {
    // 1. Baca data
    Logger.log('📖 Membaca data...');
    const players = readSheet();
    
    if (players.length === 0) {
      SpreadsheetApp.getUi().alert('❌ Tidak ada data');
      return;
    }
    
    // 2. Konfirmasi
    const confirm = SpreadsheetApp.getUi().confirm(
      '🚀 IMPORT DATA',
      `Total: ${players.length} pemain\n\nLanjutkan?`,
      SpreadsheetApp.getUi().ButtonSet.YES_NO
    );
    
    if (confirm !== SpreadsheetApp.getUi().Button.YES) {
      SpreadsheetApp.getUi().alert('❌ Dibatalkan');
      return;
    }
    
    // 3. Kirim ke API
    Logger.log('📤 Mengirim ke API...');
    const result = sendToAPI(players);
    
    // 4. Hitung waktu
    const waktu = ((new Date().getTime() - startTime) / 1000).toFixed(1);
    
    // 5. Tampilkan hasil
    showResult(result, waktu);
    
  } catch (e) {
    SpreadsheetApp.getUi().alert('❌ Error: ' + e.toString());
  }
}

// ==================== BACA SHEET ====================
function readSheet() {
  // Buka spreadsheet
  let ss;
  if (CONFIG.SHEET_ID) {
    // Pakai Sheet ID
    ss = SpreadsheetApp.openById(CONFIG.SHEET_ID);
    Logger.log('📁 Buka sheet dengan ID: ' + CONFIG.SHEET_ID);
  } else {
    // Pakai sheet aktif
    ss = SpreadsheetApp.getActiveSpreadsheet();
    Logger.log('📁 Buka sheet aktif');
  }
  
  // Buka sheet berdasarkan nama
  const sheet = ss.getSheetByName(CONFIG.SHEET_NAME);
  if (!sheet) {
    throw new Error('Sheet "' + CONFIG.SHEET_NAME + '" tidak ditemukan');
  }
  
  // Ambil data
  const lastRow = sheet.getLastRow();
  if (lastRow < CONFIG.START_ROW) return [];
  
  const data = sheet.getRange(
    CONFIG.START_ROW, 1,
    lastRow - CONFIG.START_ROW + 1,
    3
  ).getValues();
  
  // Proses data
  const players = [];
  for (let i = 0; i < data.length; i++) {
    const row = data[i];
    const userId = row[0];
    const nama = row[1];
    const poin = row[2];
    
    if (userId && userId.toString().trim()) {
      players.push({
        user_id: Number(userId.toString().replace(/\D/g, '')) || 0,
        first_name: (nama || '').toString().trim() || 'Player_' + userId,
        points: Number(poin) || 0
      });
    }
  }
  
  Logger.log(`✅ ${players.length} pemain ditemukan`);
  return players;
}

// ==================== KIRIM KE API ====================
function sendToAPI(players) {
  const url = `${CONFIG.API_URL}/bulk-import/${CONFIG.GAME_NAME}`;
  
  const options = {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'api-key': CONFIG.API_KEY
    },
    payload: JSON.stringify(players),
    muteHttpExceptions: true,
    timeout: 300000
  };
  
  const response = UrlFetchApp.fetch(url, options);
  const code = response.getResponseCode();
  
  if (code === 200) {
    return JSON.parse(response.getContentText());
  } else {
    throw new Error(`HTTP ${code}: ${response.getContentText()}`);
  }
}

// ==================== TAMPILKAN HASIL ====================
function showResult(result, waktu) {
  let msg = `✅ SUKSES!\n⏱️ ${waktu} detik\n\n`;
  
  if (result.stats) {
    msg += `📊 Total: ${result.stats.total_processed || 0}\n`;
    msg += `✅ Sukses: ${result.stats.successful || 0}\n`;
    msg += `❌ Gagal: ${result.stats.failed || 0}`;
  }
  
  SpreadsheetApp.getUi().alert('📊 HASIL', msg, SpreadsheetApp.getUi().ButtonSet.OK);
}

// ==================== TEST KONEKSI ====================
function testKoneksi() {
  try {
    const url = CONFIG.API_URL + '/health';
    const response = UrlFetchApp.fetch(url);
    const data = JSON.parse(response.getContentText());
    
    let msg = '✅ KONEKSI OK\n\n';
    msg += `🌐 ${CONFIG.API_URL}\n`;
    
    if (data.games) {
      msg += '\n📊 Game:\n';
      for (const [game, count] of Object.entries(data.games)) {
        msg += `   • ${game}: ${count} pemain\n`;
      }
    }
    
    SpreadsheetApp.getUi().alert('🔌 TEST API', msg, SpreadsheetApp.getUi().ButtonSet.OK);
    
  } catch (e) {
    SpreadsheetApp.getUi().alert('❌ Gagal: ' + e.toString());
  }
}

// ==================== LIHAT PREVIEW ====================
function lihatPreview() {
  try {
    const players = readSheet();
    const sample = players.slice(0, 5);
    
    let msg = `📋 ${players.length} pemain\n\nPreview:\n`;
    sample.forEach((p, i) => {
      msg += `${i+1}. ${p.user_id} | ${p.first_name} | ${p.points}\n`;
    });
    
    SpreadsheetApp.getUi().alert('👁️ PREVIEW', msg, SpreadsheetApp.getUi().ButtonSet.OK);
    
  } catch (e) {
    SpreadsheetApp.getUi().alert('Error: ' + e.toString());
  }
}

// ==================== MENU ====================
function onOpen() {
  const ui = SpreadsheetApp.getUi();
  ui.createMenu('📤 IMPORT MONGODB')
    .addItem('🚀 IMPORT DATA', 'importData')
    .addSeparator()
    .addItem('👁️ Preview Data', 'lihatPreview')
    .addItem('🔌 Test Koneksi', 'testKoneksi')
    .addItem('⚙️ Konfigurasi', 'lihatConfig')
    .addToUi();
}

// ==================== LIHAT KONFIGURASI ====================
function lihatConfig() {
  const msg = 
    `📌 KONFIGURASI\n\n` +
    `Game: ${CONFIG.GAME_NAME}\n` +
    `Sheet ID: ${CONFIG.SHEET_ID || 'Aktif'}\n` +
    `Sheet Name: ${CONFIG.SHEET_NAME}\n` +
    `Start Row: ${CONFIG.START_ROW}\n` +
    `Kolom: A=UserID, B=Nama, C=Poin`;
  
  SpreadsheetApp.getUi().alert('⚙️ CONFIG', msg, SpreadsheetApp.getUi().ButtonSet.OK);
}
