// routes/certificados.js
// Endpoints: buscar, ver detalle, editar, validar

const express  = require('express');
const router   = express.Router();
const pool     = require('../config/db');
const { verificarToken, requiereRol } = require('../config/auth');

router.use(verificarToken);

// ============================================================
// GET /api/certificados
// Buscar certificados con filtros y paginación
// ============================================================
router.get('/', async (req, res) => {
  try {
    const {
      q,
      numero_informe,
      anio,
      cliente,
      marca,
      magnitud,
      serie,
      identificacion,
      desde,
      hasta,
      empleado,
      orden = 'fecha_emision DESC',
      pagina = 1,
      limite = 50,
    } = req.query;

    const ordenesPermitidos = [
      'fecha_emision DESC', 'fecha_emision ASC',
      'cliente ASC', 'cliente DESC',
      'numero_informe ASC', 'numero_informe DESC',
      'marca ASC', 'marca DESC',
    ];
    const ordenFinal = ordenesPermitidos.includes(orden) ? orden : 'fecha_emision DESC';

    const offset = (parseInt(pagina) - 1) * parseInt(limite);
    const params = [];
    const condiciones = ['c.activo = TRUE'];

    if (anio) {
      params.push(parseInt(anio));
      condiciones.push(`c.anio_emision = $${params.length}`);
    }
    if (numero_informe) {
      params.push(`%${numero_informe}%`);
      condiciones.push(`c.numero_informe ILIKE $${params.length}`);
    }
    if (cliente) {
      params.push(`%${cliente}%`);
      condiciones.push(`cl.nombre ILIKE $${params.length}`);
    }
    if (marca) {
      params.push(`%${marca}%`);
      condiciones.push(`c.marca ILIKE $${params.length}`);
    }
    if (magnitud) {
      params.push(`%${magnitud}%`);
      condiciones.push(`c.magnitud_evaluada ILIKE $${params.length}`);
    }
    if (serie) {
      params.push(`%${serie}%`);
      condiciones.push(`c.numero_serie ILIKE $${params.length}`);
    }
    if (identificacion) {
      params.push(`%${identificacion}%`);
      condiciones.push(`c.identificacion ILIKE $${params.length}`);
    }
    if (desde) {
      params.push(desde);
      condiciones.push(`c.fecha_emision >= $${params.length}`);
    }
    if (hasta) {
      params.push(hasta);
      condiciones.push(`c.fecha_emision <= $${params.length}`);
    }
    if (empleado) {
      params.push(`%${empleado}%`);
      condiciones.push(`c.importado_por ILIKE $${params.length}`);
    }
    if (q) {
      params.push(`%${q}%`);
      const n = params.length;
      condiciones.push(`(
        c.numero_informe          ILIKE $${n} OR
        cl.nombre                 ILIKE $${n} OR
        c.numero_serie            ILIKE $${n} OR
        c.identificacion          ILIKE $${n} OR
        c.descripcion_instrumento ILIKE $${n} OR
        c.modelo                  ILIKE $${n} OR
        c.marca                   ILIKE $${n}
      )`);
    }

    const where = condiciones.length ? 'WHERE ' + condiciones.join(' AND ') : '';

    const totalRes = await pool.query(
      `SELECT COUNT(*) FROM certificados c LEFT JOIN clientes cl ON cl.id = c.cliente_id ${where}`,
      params
    );
    const total = parseInt(totalRes.rows[0].count);

    params.push(parseInt(limite), offset);
    const data = await pool.query(`
      SELECT
        c.id, c.numero_informe, c.anio_emision,
        cl.nombre AS nombre_cliente,
        c.descripcion_instrumento,
        c.numero_serie, c.identificacion, c.modelo, c.marca,
        c.magnitud_evaluada, c.fecha_emision, c.fecha_calibracion,
        c.importado_por
      FROM certificados c
      LEFT JOIN clientes cl ON cl.id = c.cliente_id
      ${where}
      ORDER BY ${ordenFinal.replace('cliente', 'cl.nombre')} NULLS LAST
      LIMIT $${params.length - 1} OFFSET $${params.length}
    `, params);

    res.json({
      total,
      pagina: parseInt(pagina),
      limite: parseInt(limite),
      paginas: Math.ceil(total / parseInt(limite)),
      datos: data.rows,
    });
  } catch (err) {
    console.error('Error en búsqueda de certificados:', err);
    res.status(500).json({ error: 'Error al buscar certificados.' });
  }
});

// ============================================================
// GET /api/certificados/:id
// ============================================================
router.get('/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const result = await pool.query(`
      SELECT c.*, cl.nombre AS nombre_cliente, cl.direccion, cl.atencion_a
      FROM certificados c
      LEFT JOIN clientes cl ON cl.id = c.cliente_id
      WHERE c.id = $1 AND c.activo = TRUE
    `, [id]);

    if (result.rows.length === 0) {
      return res.status(404).json({ error: 'Certificado no encontrado.' });
    }

    // Auditoría
    await pool.query(
      `INSERT INTO auditoria (usuario_id, accion, tabla, registro_id, ip_origen)
       VALUES ($1, 'VIEW', 'certificados', $2, $3)`,
      [req.usuario.id, id, req.ip]
    );

    res.json(result.rows[0]);
  } catch (err) {
    console.error('Error al obtener certificado:', err);
    res.status(500).json({ error: 'Error al obtener certificado.' });
  }
});

// ============================================================
// PUT /api/certificados/:id
// ============================================================
router.put('/:id', requiereRol('calidad'), async (req, res) => {
  try {
    const { id } = req.params;
    const {
      fecha_vencimiento,
      estado,
      descripcion_instrumento, alcance, numero_serie,
      identificacion, modelo, marca, magnitud_evaluada,
      resultado_calibracion, incertidumbre,
      temperatura, humedad_relativa,
      fecha_recepcion, fecha_calibracion, fecha_emision,
      metodo_utilizado, lugar_calibracion,
      calibrado_por, aprobado_por,
    } = req.body;

    const anterior = await pool.query('SELECT * FROM certificados WHERE id = $1', [id]);
    if (anterior.rows.length === 0) {
      return res.status(404).json({ error: 'Certificado no encontrado.' });
    }

    const result = await pool.query(`
      UPDATE certificados SET
        descripcion_instrumento = COALESCE($1,  descripcion_instrumento),
        alcance                 = COALESCE($2,  alcance),
        numero_serie            = COALESCE($3,  numero_serie),
        identificacion          = COALESCE($4,  identificacion),
        modelo                  = COALESCE($5,  modelo),
        marca                   = COALESCE($6,  marca),
        magnitud_evaluada       = COALESCE($7,  magnitud_evaluada),
        resultado_calibracion   = COALESCE($8,  resultado_calibracion),
        incertidumbre           = COALESCE($9,  incertidumbre),
        temperatura             = COALESCE($10, temperatura),
        humedad_relativa        = COALESCE($11, humedad_relativa),
        fecha_recepcion         = COALESCE($12, fecha_recepcion),
        fecha_calibracion       = COALESCE($13, fecha_calibracion),
        fecha_emision           = COALESCE($14, fecha_emision),
        metodo_utilizado        = COALESCE($15, metodo_utilizado),
        lugar_calibracion       = COALESCE($16, lugar_calibracion),
        calibrado_por           = COALESCE($17, calibrado_por),
        aprobado_por            = COALESCE($18, aprobado_por),
        fecha_vencimiento       = COALESCE($19, fecha_vencimiento),
        estado                  = COALESCE($20, estado)
      WHERE id = $21
      RETURNING *
    `, [
      descripcion_instrumento, alcance, numero_serie,
      identificacion, modelo, marca, magnitud_evaluada,
      resultado_calibracion, incertidumbre,
      temperatura, humedad_relativa,
      fecha_recepcion, fecha_calibracion, fecha_emision,
      metodo_utilizado, lugar_calibracion,
      calibrado_por, aprobado_por,
      fecha_vencimiento, estado,
      id
    ]);

    await pool.query(
      `INSERT INTO auditoria (usuario_id, accion, tabla, registro_id, datos_antes, datos_despues, ip_origen)
       VALUES ($1, 'UPDATE', 'certificados', $2, $3, $4, $5)`,
      [req.usuario.id, id, anterior.rows[0], result.rows[0], req.ip]
    );

    res.json({ mensaje: 'Certificado actualizado correctamente.', datos: result.rows[0] });
  } catch (err) {
    console.error('Error al editar certificado:', err);
    res.status(500).json({ error: 'Error al editar certificado.' });
  }
});

// ============================================================
// GET /api/certificados/:id/auditoria
// ============================================================
router.get('/:id/auditoria', async (req, res) => {
  try {
    const result = await pool.query(`
      SELECT a.*, u.nombre as usuario_nombre
      FROM auditoria a
      LEFT JOIN usuarios u ON u.id = a.usuario_id
      WHERE a.registro_id = $1 AND a.tabla = 'certificados'
      ORDER BY a.creado_en DESC
      LIMIT 50
    `, [req.params.id]);
    res.json(result.rows);
  } catch(e) {
    res.status(500).json({ error: 'Error al obtener auditoría.' });
  }
});

// ============================================================
// GET /api/certificados/stats/resumen
// ============================================================
router.get('/stats/resumen', async (req, res) => {
  try {
    const resumen = await pool.query('SELECT * FROM resumen_por_anio');
    const totalGlobal = await pool.query(
      'SELECT COUNT(*) as total FROM certificados WHERE activo = TRUE'
    );
    res.json({
      total_global: parseInt(totalGlobal.rows[0].total),
      por_anio: resumen.rows,
    });
  } catch (err) {
    console.error('Error al obtener resumen:', err);
    res.status(500).json({ error: 'Error al obtener estadísticas.' });
  }
});

module.exports = router;