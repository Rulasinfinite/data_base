// server.js
// SIDEC — Sistema de Certificados de Calibración
// Entry point principal

require('dotenv').config();
const express = require('express');
const cors    = require('cors');
const path    = require('path');

const app = express();

// ============================================================
// Middleware global
// ============================================================
app.use(cors());
app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true }));

// Archivos estáticos (frontend)
app.use(express.static(path.join(__dirname, 'public')));
app.use('/assets', express.static(path.join(__dirname, 'assets')));

// ============================================================
// Rutas API
// ============================================================
app.use('/api/usuarios',      require('./routes/usuarios'));
app.use('/api/certificados',  require('./routes/certificados'));
app.use('/api/admin',         require('./routes/admin'));

// (próximamente)
// app.use('/api/reportes',   require('./routes/reportes'));

// ============================================================
// Ruta catch-all: servir el frontend para rutas no-API
// ============================================================
app.get('*', (req, res) => {
  if (!req.path.startsWith('/api')) {
    res.sendFile(path.join(__dirname, 'public', 'index.html'));
  } else {
    res.status(404).json({ error: 'Ruta no encontrada.' });
  }
});

// ============================================================
// Iniciar servidor
// ============================================================
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log('');
  console.log('╔══════════════════════════════════════════╗');
  console.log('║   SIDEC — Certificados de Calibración    ║');
  console.log(`║   Servidor corriendo en puerto ${PORT}       ║`);
  console.log('╚══════════════════════════════════════════╝');
  console.log('');
});
