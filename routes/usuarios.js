// routes/usuarios.js
const express = require('express');
const router = express.Router();
const bcrypt = require('bcrypt');
const pool = require('../config/db');
const { generarToken, verificarToken, requiereRol, ROLES } = require('../config/auth');

let schemaReady = false;
async function ensurePermisosColumn() {
  await pool.query(`ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS permisos JSONB DEFAULT '[]'`);
}
async function ensureResetRequestsTable() {
  await pool.query(`
    CREATE TABLE IF NOT EXISTS password_reset_requests (
      id SERIAL PRIMARY KEY,
      usuario_id INTEGER REFERENCES usuarios(id),
      usuario VARCHAR(50) NOT NULL,
      nombre VARCHAR(150),
      estado VARCHAR(20) NOT NULL DEFAULT 'pendiente',
      solicitado_en TIMESTAMPTZ DEFAULT NOW()
    )
  `);
}
async function ensureUserSchema() {
  if (schemaReady) return;
  await ensurePermisosColumn();
  await ensureResetRequestsTable();
  schemaReady = true;
}

// POST /api/usuarios/login
router.post('/login', async (req, res) => {
  try {
    await ensureUserSchema();
    const { usuario, password } = req.body;
    if (!usuario || !password) {
      return res.status(400).json({ error: 'Usuario y contraseña son requeridos.' });
    }
    const result = await pool.query('SELECT * FROM usuarios WHERE usuario = $1 AND activo = TRUE', [usuario.trim()]);
    if (result.rows.length === 0) {
      return res.status(401).json({ error: 'Credenciales incorrectas.' });
    }
    const usuarioData = result.rows[0];
    const passwordOk = await bcrypt.compare(password, usuarioData.password_hash);
    if (!passwordOk) {
      return res.status(401).json({ error: 'Credenciales incorrectas.' });
    }
    await pool.query('UPDATE usuarios SET ultimo_acceso = NOW() WHERE id = $1', [usuarioData.id]);
    const token = generarToken(usuarioData);
    res.json({
      token,
      usuario: {
        id: usuarioData.id,
        nombre: usuarioData.nombre,
        usuario: usuarioData.usuario,
        rol: usuarioData.rol,
        departamento: usuarioData.departamento,
        permisos: usuarioData.permisos || [],
      },
    });
  } catch (err) {
    console.error('Error en login:', err);
    res.status(500).json({ error: 'Error al iniciar sesión.' });
  }
});

// GET /api/usuarios/me
router.get('/me', verificarToken, (req, res) => {
  res.json(req.usuario);
});

// GET /api/usuarios/perfil
router.get('/perfil', verificarToken, (req, res) => {
  res.json(req.usuario);
});

// GET /api/usuarios (listar - solo admin)
router.get('/', verificarToken, requiereRol('admin'), async (req, res) => {
  try {
    await ensureUserSchema();
    const result = await pool.query(
      `SELECT id, nombre, usuario, rol, departamento, activo, creado_en, ultimo_acceso, permisos
       FROM usuarios ORDER BY nombre ASC`
    );
    res.json(result.rows);
  } catch (err) {
    res.status(500).json({ error: 'Error al obtener usuarios.' });
  }
});

// POST /api/usuarios (crear - solo admin)
router.post('/', verificarToken, requiereRol('admin'), async (req, res) => {
  try {
    await ensureUserSchema();
    const { nombre, usuario, password, rol, departamento, permisos } = req.body;
    if (!nombre || !usuario || !password || !rol) {
      return res.status(400).json({ error: 'Nombre, usuario, contraseña y rol son requeridos.' });
    }
    if (password.length < 8 || password.length > 15) {
      return res.status(400).json({ error: 'La contraseña debe tener entre 8 y 15 caracteres.' });
    }
    if (!ROLES.includes(rol)) {
      return res.status(400).json({ error: `Rol inválido. Opciones: ${ROLES.join(', ')}` });
    }
    const hash = await bcrypt.hash(password, 10);
    const permisosArray = permisos || [];
    const result = await pool.query(
      `INSERT INTO usuarios (nombre, usuario, password_hash, rol, departamento, permisos)
       VALUES ($1, $2, $3, $4, $5, $6) RETURNING id, nombre, usuario, rol, departamento, permisos`,
      [nombre, usuario.trim(), hash, rol, departamento, permisosArray]
    );
    res.status(201).json({ mensaje: 'Usuario creado correctamente.', usuario: result.rows[0] });
  } catch (err) {
    if (err.code === '23505') {
      return res.status(409).json({ error: 'Ya existe un usuario con ese nombre de usuario.' });
    }
    res.status(500).json({ error: 'Error al crear usuario.' });
  }
});

// PUT /api/usuarios/:id (editar - solo admin)
router.put('/:id', verificarToken, requiereRol('admin'), async (req, res) => {
  try {
    await ensureUserSchema();
    const { id } = req.params;
    const { nombre, rol, departamento, activo, password, permisos } = req.body;
    let hashNuevo = null;
    if (password) {
      hashNuevo = await bcrypt.hash(password, 10);
    }
    const permisosArray = permisos || [];
    await pool.query(`
      UPDATE usuarios SET
        nombre       = COALESCE($1, nombre),
        rol          = COALESCE($2, rol),
        departamento = COALESCE($3, departamento),
        activo       = COALESCE($4, activo),
        password_hash = COALESCE($5, password_hash),
        permisos     = COALESCE($6, permisos)
      WHERE id = $7
    `, [nombre, rol, departamento, activo, hashNuevo, permisosArray, id]);
    res.json({ mensaje: 'Usuario actualizado correctamente.' });
  } catch (err) {
    res.status(500).json({ error: 'Error al actualizar usuario.' });
  }
});

// DELETE /api/usuarios/:id (desactivar - solo admin)
router.delete('/:id', verificarToken, requiereRol('admin'), async (req, res) => {
  try {
    await ensureUserSchema();
    const { id } = req.params;

    const adminCount = await pool.query(
      'SELECT COUNT(*) AS total FROM usuarios WHERE rol = $1 AND activo = TRUE',
      ['admin']
    );
    const totalAdmins = parseInt(adminCount.rows[0].total, 10);

    const usuarioRes = await pool.query('SELECT rol FROM usuarios WHERE id = $1', [id]);
    if (usuarioRes.rows.length === 0) {
      return res.status(404).json({ error: 'Usuario no encontrado.' });
    }
    if (totalAdmins === 1 && usuarioRes.rows[0].rol === 'admin') {
      return res.status(400).json({ error: 'No puede desactivar el único administrador del sistema.' });
    }

    await pool.query('UPDATE usuarios SET activo = FALSE WHERE id = $1', [id]);
    res.json({ mensaje: 'Usuario desactivado correctamente.' });
  } catch (err) {
    res.status(500).json({ error: 'Error al desactivar usuario.' });
  }
});

// POST /api/usuarios/:id/reset-password (restablecer contraseña - admin)
router.post('/:id/reset-password', verificarToken, requiereRol('admin'), async (req, res) => {
  try {
    await ensureUserSchema();
    const { id } = req.params;
    const caracteres = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789@#$!';
    let nuevaPassword = '';
    while (nuevaPassword.length < 10) {
      nuevaPassword += caracteres[Math.floor(Math.random() * caracteres.length)];
    }

    const hash = await bcrypt.hash(nuevaPassword, 10);
    await pool.query('UPDATE usuarios SET password_hash = $1 WHERE id = $2', [hash, id]);
    await pool.query(
      "UPDATE password_reset_requests SET estado = 'procesado' WHERE usuario_id = $1 AND estado = 'pendiente'",
      [id]
    );

    res.json({ mensaje: 'Contraseña restablecida correctamente.', nueva_password: nuevaPassword });
  } catch (err) {
    console.error('Error al restablecer contraseña:', err);
    res.status(500).json({ error: 'Error al restablecer contraseña.' });
  }
});

// POST /api/usuarios/solicitar-reset
router.post('/solicitar-reset', async (req, res) => {
  try {
    await ensureUserSchema();
    const { usuario } = req.body;
    if (!usuario) {
      return res.status(400).json({ error: 'Nombre de usuario es requerido.' });
    }
    const username = usuario.trim();
    const userResult = await pool.query('SELECT id, nombre FROM usuarios WHERE usuario = $1 AND activo = TRUE', [username]);
    const usuarioId = userResult.rows.length ? userResult.rows[0].id : null;
    const nombre = userResult.rows.length ? userResult.rows[0].nombre : null;

    await pool.query(
      `INSERT INTO password_reset_requests (usuario_id, usuario, nombre, estado)
       VALUES ($1, $2, $3, 'pendiente')`,
      [usuarioId, username, nombre]
    );

    res.json({ mensaje: 'Solicitud de recuperación enviada.' });
  } catch (err) {
    console.error('Error en solicitud de recuperación:', err);
    res.status(500).json({ error: 'No se pudo registrar la solicitud.' });
  }
});

// GET /api/usuarios/reset-solicitudes (solo admin)
router.get('/reset-solicitudes', verificarToken, requiereRol('admin'), async (req, res) => {
  try {
    await ensureUserSchema();
    const result = await pool.query(
      `SELECT id, usuario, nombre, estado, solicitado_en
       FROM password_reset_requests
       WHERE estado = 'pendiente'
       ORDER BY solicitado_en DESC
       LIMIT 50`
    );
    res.json(result.rows);
  } catch (err) {
    console.error('Error al obtener solicitudes de recuperación:', err);
    res.status(500).json({ error: 'Error al obtener solicitudes de recuperación.' });
  }
});

// POST /api/usuarios/cambiar-password
router.post('/cambiar-password', verificarToken, async (req, res) => {
  try {
    await ensureUserSchema();
    const { password_actual, password_nuevo } = req.body;
    if (!password_actual || !password_nuevo) {
      return res.status(400).json({ error: 'Contraseña actual y nueva son requeridas.' });
    }
    if (password_nuevo.length < 8) {
      return res.status(400).json({ error: 'La nueva contraseña debe tener al menos 8 caracteres.' });
    }

    const userResult = await pool.query('SELECT password_hash FROM usuarios WHERE id = $1', [req.usuario.id]);
    if (userResult.rows.length === 0) {
      return res.status(404).json({ error: 'Usuario no encontrado.' });
    }

    const passwordOk = await bcrypt.compare(password_actual, userResult.rows[0].password_hash);
    if (!passwordOk) {
      return res.status(401).json({ error: 'La contraseña actual es incorrecta.' });
    }

    const hash = await bcrypt.hash(password_nuevo, 10);
    await pool.query('UPDATE usuarios SET password_hash = $1 WHERE id = $2', [hash, req.usuario.id]);
    res.json({ mensaje: 'Contraseña actualizada correctamente.' });
  } catch (err) {
    console.error('Error al cambiar contraseña:', err);
    res.status(500).json({ error: 'Error al cambiar la contraseña.' });
  }
});

module.exports = router;