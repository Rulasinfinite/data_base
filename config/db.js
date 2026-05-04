// config/db.js
// Conexión a PostgreSQL - sidec_db
// NOTA: "sidecmexico" es solo el nombre del servidor en pgAdmin (etiqueta visual).
//       Node.js se conecta a la dirección real: localhost

const { Pool } = require('pg');

const pool = new Pool({
  host:     process.env.DB_HOST     || 'localhost',   // <-- localhost, no "sidecmexico"
  port:     parseInt(process.env.DB_PORT) || 5432,
  database: process.env.DB_NAME     || 'sidec_db',
  user:     process.env.DB_USER     || 'postgres',
  password: process.env.DB_PASSWORD || 'sidecmexico',
  max:      20,
  idleTimeoutMillis:    30000,
  connectionTimeoutMillis: 5000,
});

// Verificar conexión al iniciar
pool.connect((err, client, release) => {
  if (err) {
    console.error('❌ Error conectando a PostgreSQL:', err.message);
    console.error('   Host:', process.env.DB_HOST || 'localhost');
    console.error('   Base:', process.env.DB_NAME || 'sidec_db');
    console.error('   User:', process.env.DB_USER || 'postgres');
    return;
  }
  release();
  console.log('✅ Conectado a PostgreSQL — sidec_db');
});

module.exports = pool;
