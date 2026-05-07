// routes/certificados.js
// Endpoints: buscar, ver detalle, editar, validar

const express  = require('express');
const router   = express.Router();
const pool     = require('../config/db');
const { verificarToken, requiereRol } = require('../config/auth');

// Todas las rutas de certificados requieren sesión activa
router.use(verificarToken);

// ============================================================
// GET /api/certificados
// Buscar certificados con filtros y paginación
// ============================================================
router.get('/', async (req, res) => {
  try {
    const {
      q,               // búsqueda general
      numero_informe,  // número de informe (nuevo filtro)
      anio,            // año de emisión
      cliente,         // nombre del cliente
      marca,           // marca del instrumento
      magnitud,        // magnitud evaluada
      serie,           // número de serie
      identificacion,  // identificación del instrumento
      desde,           // fecha emisión desde (YYYY-MM-DD)
      hasta,           // fecha emisión hasta (YYYY-MM-DD)
      empleado,        // código de empleado (para importaciones)
      orden = 'fecha_emision DESC',
      pagina = 1,
      limite = 50,
    } = req.query;

    // Validar orden para evitar SQL injection
    const ordenesPermitidos = [
      'fecha_emision DESC', 'fecha_emision ASC',
      'nombre_cliente ASC', 'nombre_cliente DESC',
      'numero_informe ASC', 'numero_informe DESC',
      'marca ASC', 'marca DESC',
    ];
    const ordenFinal = ordenesPermitidos.includes(orden)
      ? orden : 'fecha_emision DESC';

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
      condiciones.push(`c.nombre_cliente ILIKE $${params.length}`);
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
        c.nombre_cliente          ILIKE $${n} OR
        c.numero_serie            ILIKE $${n} OR
        c.identificacion          ILIKE $${n} OR
        c.descripcion_instrumento ILIKE $${n} OR
        c.modelo                  ILIKE $${n} OR
        c.marca                   ILIKE $${n} OR
        c.atencion_a              ILIKE $${n}
      )`);
    }

    const where = condiciones.length ? 'WHERE ' + condiciones.join(' AND ') : '';

    // Total de registros
    const totalRes = await pool.query(
      `SELECT COUNT(*) FROM certificados c ${where}`, params
    );
    const total = parseInt(totalRes.rows[0].count);

    // Registros de la página actual
    params.push(parseInt(limite), offset);
    const data = await pool.query(`
      SELECT
        c.id, c.numero_informe, c.anio_emision,
        c.nombre_cliente, c.atencion_a, c.descripcion_instrumento,
        c.numero_serie, c.identificacion, c.modelo, c.marca,
        c.magnitud_evaluada, c.fecha_emision, c.fecha_calibracion,
        c.importado_por
      FROM certificados c
      ${where}
      ORDER BY c.${ordenFinal} NULLS LAST
      LIMIT $${params.length - 1} OFFSET $${params.length}
    `, params);

    res.json({
      total,
      pagina:   parseInt(pagina),
      limite:   parseInt(limite),
      paginas:  Math.ceil(total / parseInt(limite)),
      datos:    data.rows,
    });
  } catch (err) {
    console.error('Error en búsqueda de certificados:', err);
    res.status(500).json({ error: 'Error al buscar certificados.' });
  }
});

// ============================================================
// GET /api/certificados/:id
// Ver detalle completo de un certificado
// ============================================================
router.get('/:id', async (req, res) => {
  try {
    const { id } = req.params;
    const result = await pool.query(
      'SELECT * FROM certificados WHERE id = $1 AND activo = TRUE',
      [id]
    );

    if (result.rows.length === 0) {
      return res.status(404).json({ error: 'Certificado no encontrado.' });
    }

    // Registrar consulta en auditoría
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
// Editar certificado (solo rol: calidad o admin)
// ============================================================
router.put('/:id', requiereRol('calidad'), async (req, res) => {
  try {
    const { id } = req.params;
    const {
      nombre_cliente, direccion, atencion_a,
      descripcion_instrumento, alcance, numero_serie,
      identificacion, modelo, marca, magnitud_evaluada,
      resultado_calibracion, incertidumbre,
      temperatura, humedad_relativa,
      fecha_recepcion, fecha_calibracion, fecha_emision,
      metodo_utilizado, lugar_calibracion,
      calibrado_por, aprobado_por,
    } = req.body;

    // Guardar datos anteriores para auditoría
    const anterior = await pool.query(
      'SELECT * FROM certificados WHERE id = $1',
      [id]
    );
    if (anterior.rows.length === 0) {
      return res.status(404).json({ error: 'Certificado no encontrado.' });
    }

    const result = await pool.query(`
      UPDATE certificados SET
        nombre_cliente          = COALESCE($1,  nombre_cliente),
        direccion               = COALESCE($2,  direccion),
        atencion_a              = COALESCE($3,  atencion_a),
        descripcion_instrumento = COALESCE($4,  descripcion_instrumento),
        alcance                 = COALESCE($5,  alcance),
        numero_serie            = COALESCE($6,  numero_serie),
        identificacion          = COALESCE($7,  identificacion),
        modelo                  = COALESCE($8,  modelo),
        marca                   = COALESCE($9,  marca),
        magnitud_evaluada       = COALESCE($10, magnitud_evaluada),
        resultado_calibracion   = COALESCE($11, resultado_calibracion),
        incertidumbre           = COALESCE($12, incertidumbre),
        temperatura             = COALESCE($13, temperatura),
        humedad_relativa        = COALESCE($14, humedad_relativa),
        fecha_recepcion         = COALESCE($15, fecha_recepcion),
        fecha_calibracion       = COALESCE($16, fecha_calibracion),
        fecha_emision           = COALESCE($17, fecha_emision),
        metodo_utilizado        = COALESCE($18, metodo_utilizado),
        lugar_calibracion       = COALESCE($19, lugar_calibracion),
        calibrado_por           = COALESCE($20, calibrado_por),
        aprobado_por            = COALESCE($21, aprobado_por)
      WHERE id = $22
      RETURNING *
    `, [
      nombre_cliente, direccion, atencion_a,
      descripcion_instrumento, alcance, numero_serie,
      identificacion, modelo, marca, magnitud_evaluada,
      resultado_calibracion, incertidumbre,
      temperatura, humedad_relativa,
      fecha_recepcion, fecha_calibracion, fecha_emision,
      metodo_utilizado, lugar_calibracion,
      calibrado_por, aprobado_por,
      id
    ]);

    // Registrar cambio en auditoría
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
// Historial de cambios de un certificado
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
// Resumen general para el dashboard
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