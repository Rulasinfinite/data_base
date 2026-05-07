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

// ── Rutas absolutas ───────────────────────────────────────
const PROJECT_ROOT = path.join(__dirname, '..');
const SCRIPT_PATH  = path.join(PROJECT_ROOT, 'scripts', 'importar_masivo.py');
const PYTHON_EXE   = path.join(PROJECT_ROOT, 'venv', 'Scripts', 'python.exe');

// ── Almacenamiento temporal de progreso (en memoria) ─────
const progresos = {};

// ============================================================
// POST /api/admin/escanear
// ============================================================
router.post('/escanear', async (req, res) => {
  const { ruta, empleado, anio } = req.body;
  if (!ruta) return res.status(400).json({ error: 'Ruta requerida.' });

  if (!fs.existsSync(ruta)) {
    return res.json({
      total: 0,
      por_tipo: { excel: 0, pdf: 0 },
      archivos: [],
      advertencia: `Carpeta no encontrada en el servidor: ${ruta}`,
    });
  }

  try {
    const args = ['--solo-escanear', '--json-output', '--carpeta', ruta];
    if (empleado) args.push('--empleado', empleado);
    if (anio)     args.push('--anio', String(anio));

    const resultado = await ejecutarPython(args);

    if (resultado.jsonData) {
      const d = resultado.jsonData;
      return res.json({
        total:    d.total    || 0,
        por_tipo: d.por_tipo || { excel: 0, pdf: 0 },
        archivos: d.archivos || [],
        subarbol: construirSubarbol(ruta, anio),
      });
    }

    res.json({
      total:    0,
      por_tipo: { excel: 0, pdf: 0 },
      archivos: [],
      subarbol: construirSubarbol(ruta, anio),
      _debug:   resultado.stderr || '',
    });
  } catch (e) {
    console.error('[escanear] Error:', e.message);
    const conteo = contarArchivosLocal(ruta);
    res.json({
      total:    conteo.total,
      por_tipo: conteo.por_tipo,
      archivos: [],
      subarbol: construirSubarbol(ruta, anio),
      advertencia: `Python no disponible: ${e.message}.`,
    });
  }
});

// ============================================================
// POST /api/admin/importar
// ============================================================
router.post('/importar', async (req, res) => {
  const {
    carpetas      = [],
    soloEscanear  = false,
    skipDuplicados = true,
    procesarPdf   = true,
  } = req.body;

  if (!carpetas.length) {
    return res.status(400).json({ error: 'Se requiere al menos una carpeta.' });
  }

  let importacion_id = null;
  try {
    const result = await pool.query(
      `INSERT INTO importaciones (usuario_id, carpeta_origen, estado)
       VALUES ($1, $2, 'en_proceso') RETURNING id`,
      [req.usuario.id, carpetas.map(c => c.ruta).join(', ')]
    );
    importacion_id = result.rows[0].id;
  } catch (e) {
    console.warn('[importar] No se pudo registrar en BD:', e.message);
  }

  const inicio = Date.now();
  let totalArchivos = 0;
  let exitosos      = 0;
  let fallidos      = 0;
  let noCerts       = 0;
  let omitidos      = 0;
  const erroresTotal = [];

  try {
    for (const carpeta of carpetas) {
      const args = ['--json-output', '--carpeta', carpeta.ruta];
      if (carpeta.empleado) args.push('--empleado', carpeta.empleado);
      if (carpeta.anio)     args.push('--anio', String(carpeta.anio));
      if (soloEscanear)     args.push('--solo-escanear');

      const resultado = await ejecutarPython(args, importacion_id);

      if (resultado.jsonData) {
        const d = resultado.jsonData;
        totalArchivos += d.total           || 0;
        exitosos      += d.exitosos        || 0;
        fallidos      += d.fallidos        || 0;
        noCerts       += d.no_certificados || 0;
        omitidos      += d.omitidos        || 0;
        if (Array.isArray(d.errores)) {
          erroresTotal.push(...d.errores.slice(0, 50));
        }
      } else {
        const stats = parsearResumen(resultado.stdout);
        totalArchivos += stats.total    || 0;
        exitosos      += stats.exitosos || 0;
        fallidos      += stats.fallidos || 0;
        noCerts       += stats.noCerts  || 0;
      }
    }

    const duracion = ((Date.now() - inicio) / 1000).toFixed(1) + 's';

    if (importacion_id) {
      await pool.query(
        `UPDATE importaciones SET
           total_archivos=$1, exitosos=$2, fallidos=$3,
           omitidos=$4, errores=$5, finalizado_en=NOW(), estado=$6
         WHERE id=$7`,
        [
          totalArchivos, exitosos, fallidos, omitidos,
          JSON.stringify(erroresTotal.slice(0, 100)),
          fallidos > 0 ? 'con_errores' : 'completado',
          importacion_id,
        ]
      );
      // Limpiar progreso al finalizar
      delete progresos[importacion_id];
    }

    res.json({
      importacion_id,
      total:    totalArchivos,
      exitosos,
      fallidos,
      no_certs: noCerts,
      omitidos,
      duracion,
      errores:  erroresTotal.slice(0, 100),
    });

  } catch (e) {
    console.error('[importar] Error:', e.message);
    if (importacion_id) {
      await pool.query(
        `UPDATE importaciones SET estado='con_errores', finalizado_en=NOW() WHERE id=$1`,
        [importacion_id]
      ).catch(() => {});
      delete progresos[importacion_id];
    }
    res.status(500).json({ error: e.message });
  }
});

// ============================================================
// GET /api/admin/importaciones — historial
// ============================================================
router.get('/importaciones', async (req, res) => {
  try {
    const result = await pool.query(`
      SELECT i.*, u.nombre AS usuario_nombre
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
// GET /api/admin/progreso/:id — progreso en tiempo real
// ============================================================
router.get('/progreso/:id', (req, res) => {
  const { id } = req.params;
  const prog = progresos[id] || { actual: 0, total: 0, pct: 0 };
  res.json(prog);
});

// ============================================================
// GET /api/admin/verificar-python
// ============================================================
router.get('/verificar-python', (req, res) => {
  const pythonExiste = fs.existsSync(PYTHON_EXE);
  const scriptExiste = fs.existsSync(SCRIPT_PATH);
  res.json({
    python_exe:     PYTHON_EXE,
    python_existe:  pythonExiste,
    script_path:    SCRIPT_PATH,
    script_existe:  scriptExiste,
    project_root:   PROJECT_ROOT,
    ok:             pythonExiste && scriptExiste,
    mensaje: (!pythonExiste)
      ? `Python del venv no encontrado en: ${PYTHON_EXE}. Crea el venv con: python -m venv venv`
      : (!scriptExiste)
      ? `Script no encontrado en: ${SCRIPT_PATH}`
      : 'Todo OK',
  });
});

// ============================================================
// HELPERS
// ============================================================

function ejecutarPython(args, importacion_id = null) {
  return new Promise((resolve, reject) => {
    if (!fs.existsSync(PYTHON_EXE)) {
      return reject(new Error(`Python del venv no encontrado: ${PYTHON_EXE}`));
    }

    const proc = spawn(PYTHON_EXE, [SCRIPT_PATH, ...args], {
      cwd: PROJECT_ROOT,
      windowsHide: true,
    });

    proc.stdout.setEncoding('utf8');
    proc.stderr.setEncoding('utf8');

    let stdout = '';
    let stderr = '';

    proc.stdout.on('data', d => { stdout += d; });

    proc.stderr.on('data', d => {
      stderr += d;
      // Buscar líneas de progreso "Procesados X/Total..."
      const lineas = d.toString().split('\n');
      lineas.forEach(linea => {
        const match = linea.match(/Procesados (\d+)\/(\d+)/);
        if (match && importacion_id) {
          const actual = parseInt(match[1]);
          const total = parseInt(match[2]);
          progresos[importacion_id] = {
            actual,
            total,
            pct: Math.round((actual / total) * 100)
          };
        }
      });
    });

    proc.on('close', code => {
      if (stderr) console.log('[python stderr]', stderr.slice(0, 800));

      let jsonData = null;
      const match = stdout.match(/__JSON_START__\r?\n([\s\S]*?)\r?\n__JSON_END__/);
      if (match) {
        try { jsonData = JSON.parse(match[1]); } catch (e) {
          console.warn('[python] JSON inválido:', e.message);
        }
      }

      resolve({ stdout, stderr, code, jsonData });
    });

    proc.on('error', err => {
      reject(new Error(`Error al lanzar Python: ${err.message}`));
    });

    const timer = setTimeout(() => {
      proc.kill();
      reject(new Error('Timeout: la operación tardó más de 4 horas.'));
    }, 4 * 60 * 60 * 1000);

    proc.on('close', () => clearTimeout(timer));
  });
}

function parsearResumen(stdout) {
  const stats = { total: 0, exitosos: 0, fallidos: 0, noCerts: 0 };
  stdout.split('\n').forEach(line => {
    const m = (pat) => { const r = line.match(pat); return r ? parseInt(r[1]) : null; };
    stats.total    = m(/Total archivos[^:]*:\s*(\d+)/i)    ?? stats.total;
    stats.exitosos = m(/[Éé]xito[^:]*:\s*(\d+)/i)         ?? stats.exitosos;
    stats.exitosos = m(/Importados?[^:]*:\s*(\d+)/i)       ?? stats.exitosos;
    stats.fallidos = m(/Fallidos?[^:]*:\s*(\d+)/i)         ?? stats.fallidos;
    stats.noCerts  = m(/no.*certific[^:]*:\s*(\d+)/i)      ?? stats.noCerts;
  });
  return stats;
}

function contarArchivosLocal(ruta) {
  const resultado = { total: 0, por_tipo: { excel: 0, pdf: 0 } };
  try {
    const recorrer = (dir) => {
      const items = fs.readdirSync(dir, { withFileTypes: true });
      items.forEach(item => {
        if (item.name.startsWith('~$')) return;
        const rutaItem = path.join(dir, item.name);
        if (item.isDirectory()) {
          recorrer(rutaItem);
        } else {
          const ext = path.extname(item.name).toLowerCase();
          if (['.xlsx', '.xls'].includes(ext)) {
            resultado.total++;
            resultado.por_tipo.excel++;
          } else if (ext === '.pdf') {
            resultado.total++;
            resultado.por_tipo.pdf++;
          }
        }
      });
    };
    recorrer(ruta);
  } catch {}
  return resultado;
}

function construirSubarbol(ruta, anioFiltro) {
  try {
    const items = fs.readdirSync(ruta, { withFileTypes: true });
    return items.slice(0, 50).map(item => {
      if (item.isDirectory()) {
        const esAnio = /^20[1-3]\d$/.test(item.name);
        const esMes  = /^(0?[1-9]|1[0-2])/.test(item.name);
        return { nombre: item.name, tipo: esAnio ? 'anio' : esMes ? 'mes' : 'carpeta' };
      }
      const ext = path.extname(item.name).toLowerCase();
      if (['.xlsx', '.xls', '.pdf'].includes(ext)) {
        return { nombre: item.name, tipo: 'archivo' };
      }
      return null;
    }).filter(Boolean);
  } catch { return []; }
}

module.exports = router;