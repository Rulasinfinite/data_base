// routes/admin.js
// Endpoints: escanear carpetas, iniciar importación, historial
// Conectado con scripts/importar_masivo.py

const express = require('express');
const router  = express.Router();
const { spawn } = require('child_process');
const path  = require('path');
const fs    = require('fs');
const pool  = require('../config/db');
const { verificarToken, requiereRol } = require('../config/auth');

// Todas las rutas de admin requieren rol admin
router.use(verificarToken, requiereRol('admin'));

const SCRIPT_PATH = path.join(__dirname, '..', 'scripts', 'importar_masivo.py');

// ============================================================
// POST /api/admin/escanear
// Escanea una carpeta y devuelve estructura de archivos
// ============================================================
router.post('/escanear', async (req, res) => {
  const { ruta, empleado, anio } = req.body;

  if (!ruta) return res.status(400).json({ error: 'Ruta requerida.' });

  try {
    // Verificar que la carpeta existe (si es ruta local al servidor)
    const existe = fs.existsSync(ruta);
    if (!existe) {
      // Si no existe localmente, devolver respuesta simulada para pruebas
      return res.json({
        total: 0,
        por_tipo: { excel: 0, pdf: 0, skip: 0 },
        por_anio: {},
        por_empleado: {},
        subarbol: [],
        advertencia: `Carpeta no encontrada en el servidor: ${ruta}. Verifica la ruta.`
      });
    }

    // Ejecutar script Python en modo --solo-escanear
    const args = [SCRIPT_PATH, '--solo-escanear', '--carpeta', ruta];
    if (empleado) args.push('--empleado', empleado);
    if (anio)     args.push('--anio', anio);

    const resultado = await ejecutarPython(args);
    const stats = parsearEstadisticasScan(resultado.stdout);

    // Construir subarbol visual desde la carpeta
    const subarbol = construirSubarbol(ruta, anio);

    res.json({
      total:        stats.total || 0,
      por_tipo:     stats.por_tipo || {},
      por_anio:     stats.por_anio || {},
      por_empleado: stats.por_empleado || {},
      subarbol,
    });

  } catch (e) {
    console.error('Error escanear:', e);
    res.status(500).json({ error: e.message });
  }
});

// ============================================================
// POST /api/admin/importar
// Ejecuta la importación masiva
// ============================================================
router.post('/importar', async (req, res) => {
  const {
    carpetas = [],
    soloEscanear = false,
    skipDuplicados = true,
    procesarPdf = true,
  } = req.body;

  if (!carpetas.length) {
    return res.status(400).json({ error: 'Se requiere al menos una carpeta.' });
  }

  // Registrar inicio en la tabla importaciones
  let importacion_id = null;
  try {
    const result = await pool.query(
      `INSERT INTO importaciones (usuario_id, carpeta_origen, estado)
       VALUES ($1, $2, 'en_proceso') RETURNING id`,
      [req.usuario.id, carpetas.map(c => c.ruta).join(', ')]
    );
    importacion_id = result.rows[0].id;
  } catch (e) {
    console.warn('No se pudo registrar importación en BD:', e.message);
  }

  const inicio = Date.now();
  const erroresTotal = [];
  let totalArchivos  = 0;
  let exitosos       = 0;
  let fallidos       = 0;
  let noCerts        = 0;

  try {
    for (const carpeta of carpetas) {
      const args = [SCRIPT_PATH, '--carpeta', carpeta.ruta];
      if (carpeta.empleado) args.push('--empleado', carpeta.empleado);
      if (carpeta.anio)     args.push('--anio', carpeta.anio);
      if (soloEscanear)     args.push('--solo-escanear');

      const resultado = await ejecutarPython(args);
      const stats = parsearResumen(resultado.stdout);

      totalArchivos += stats.total    || 0;
      exitosos      += stats.exitosos || 0;
      fallidos      += stats.fallidos || 0;
      noCerts       += stats.noCerts  || 0;

      if (resultado.erroresJSON) {
        erroresTotal.push(...resultado.erroresJSON);
      }
    }

    const duracion = ((Date.now() - inicio) / 1000).toFixed(1) + 's';

    // Actualizar registro de importación
    if (importacion_id) {
      await pool.query(
        `UPDATE importaciones SET
           total_archivos=$1, exitosos=$2, fallidos=$3,
           errores=$4, finalizado_en=NOW(),
           estado=$5
         WHERE id=$6`,
        [
          totalArchivos, exitosos, fallidos,
          JSON.stringify(erroresTotal.slice(0, 100)),
          fallidos > 0 ? 'con_errores' : 'completado',
          importacion_id
        ]
      );
    }

    res.json({
      total:    totalArchivos,
      exitosos,
      fallidos,
      no_certs: noCerts,
      duracion,
      errores:  erroresTotal.slice(0, 100),
    });

  } catch (e) {
    console.error('Error importar:', e);
    if (importacion_id) {
      await pool.query(
        `UPDATE importaciones SET estado='con_errores', finalizado_en=NOW() WHERE id=$1`,
        [importacion_id]
      );
    }
    res.status(500).json({ error: e.message });
  }
});

// ============================================================
// GET /api/admin/importaciones
// Historial de importaciones
// ============================================================
router.get('/importaciones', async (req, res) => {
  try {
    const result = await pool.query(`
      SELECT i.*, u.nombre as usuario_nombre
      FROM importaciones i
      LEFT JOIN usuarios u ON u.id = i.usuario_id
      ORDER BY i.iniciado_en DESC
      LIMIT 50
    `);
    res.json(result.rows);
  } catch (e) {
    res.status(500).json({ error: 'Error al obtener historial.' });
  }
});

// ============================================================
// Helpers
// ============================================================

// Ejecuta el script Python y devuelve stdout/stderr
function ejecutarPython(args) {
  return new Promise((resolve, reject) => {
    const proc = spawn('python', args, { encoding: 'utf8' });
    let stdout = '';
    let stderr = '';

    proc.stdout.on('data', d => { stdout += d; });
    proc.stderr.on('data', d => { stderr += d; });

    proc.on('close', code => {
      // Intentar leer archivo de errores JSON si existe
      let erroresJSON = [];
      try {
        const files = fs.readdirSync('.').filter(f => f.startsWith('errores_') && f.endsWith('.json'));
        if (files.length > 0) {
          const newest = files.sort().pop();
          erroresJSON = JSON.parse(fs.readFileSync(newest, 'utf8'));
          fs.unlinkSync(newest); // limpiar
        }
      } catch {}

      resolve({ stdout, stderr, code, erroresJSON });
    });

    proc.on('error', err => reject(new Error(`Error al ejecutar Python: ${err.message}`)));

    // Timeout de 30 minutos para importaciones grandes
    setTimeout(() => {
      proc.kill();
      reject(new Error('Timeout: la importación tardó más de 30 minutos.'));
    }, 30 * 60 * 1000);
  });
}

// Parsea el resumen final del script Python
function parsearResumen(stdout) {
  const stats = { total: 0, exitosos: 0, fallidos: 0, noCerts: 0 };
  const lines = stdout.split('\n');
  lines.forEach(line => {
    const total    = line.match(/Total archivos procesados\s*:\s*(\d+)/i);
    const exito    = line.match(/[Éé]xitos?\s*:\s*(\d+)/i);
    const fallo    = line.match(/Fallidos?\s*:\s*(\d+)/i);
    const noCert   = line.match(/no.*certificados?\s*:\s*(\d+)/i);
    if (total)  stats.total    = parseInt(total[1]);
    if (exito)  stats.exitosos = parseInt(exito[1]);
    if (fallo)  stats.fallidos = parseInt(fallo[1]);
    if (noCert) stats.noCerts  = parseInt(noCert[1]);
  });
  return stats;
}

// Parsea estadísticas del modo --solo-escanear
function parsearEstadisticasScan(stdout) {
  const stats = { total: 0, por_tipo: {}, por_anio: {}, por_empleado: {} };
  const lines = stdout.split('\n');
  let seccion = null;

  lines.forEach(line => {
    const totalM = line.match(/Total archivos encontrados\s*:\s*(\d+)/i);
    if (totalM) { stats.total = parseInt(totalM[1]); return; }

    if (line.includes('Por empleado')) { seccion = 'empleado'; return; }
    if (line.includes('Por año'))      { seccion = 'anio';     return; }
    if (line.includes('Por tipo'))     { seccion = 'tipo';     return; }

    const item = line.match(/^\s+(.+?)\s+(\d+)\s+archivos/i);
    if (item) {
      const key = item[1].trim();
      const val = parseInt(item[2]);
      if (seccion === 'empleado') stats.por_empleado[key] = val;
      if (seccion === 'anio')     stats.por_anio[key]     = val;
      if (seccion === 'tipo')     stats.por_tipo[key]     = val;
    }
  });
  return stats;
}

// Construye subarbol visual leyendo la carpeta
function construirSubarbol(ruta, anioFiltro) {
  try {
    const items = fs.readdirSync(ruta, { withFileTypes: true });
    return items.slice(0, 30).map(item => {
      if (item.isDirectory()) {
        const esAnio = /^20[1-3]\d$/.test(item.name);
        const esMes  = /^(0?[1-9]|1[0-2])/.test(item.name);
        return {
          nombre: item.name,
          tipo:   esAnio ? 'anio' : esMes ? 'mes' : 'carpeta',
          hijos:  null,
        };
      } else {
        const ext = path.extname(item.name).toLowerCase();
        if (['.xlsx','.xls','.pdf'].includes(ext)) {
          return { nombre: item.name, tipo: 'archivo' };
        }
        return null;
      }
    }).filter(Boolean);
  } catch {
    return [];
  }
}

module.exports = router;
