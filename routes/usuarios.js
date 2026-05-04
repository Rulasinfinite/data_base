// routes/usuarios.js
// Login, logout, perfil y gestión de usuarios (admin)

const express  = require('express');
const router   = express.Router();
const bcrypt   = require('bcrypt');
const pool     = require('../config/db');
const { generarToken, verificarToken, requiereRol, ROLES } = require('../config/auth');

// ============================================================
// POST /api/usuarios/login
// ============================================================
router.post('/login', async (req, res) => {
  try {
    const { usuario, password } = req.body;

    if (!usuario || !password) {
      return res.status(400).json({ error: 'Usuario y contraseña son requeridos.' });
    }

    const result = await pool.query(
      'SELECT * FROM usuarios WHERE usuario = $1 AND activo = TRUE',
      [usuario.trim()]
    );

    if (result.rows.length === 0) {
      return res.status(401).json({ error: 'Credenciales incorrectas.' });
    }

    const usuario = result.rows[0];
    const passwordOk = await bcrypt.compare(password, usuario.password_hash);

    if (!passwordOk) {
      return res.status(401).json({ error: 'Credenciales incorrectas.' });
    }

    // Actualizar último acceso
    await pool.query(
      'UPDATE usuarios SET ultimo_acceso = NOW() WHERE id = $1',
      [usuario.id]
    );

    const token = generarToken(usuario);

    res.json({
      token,
      usuario: {
        id:           usuario.id,
        nombre:       usuario.nombre,
        usuario:      usuario.usuario,
        rol:          usuario.rol,
        departamento: usuario.departamento,
      },
    });
  } catch (err) {
    console.error('Error en login:', err);
    res.status(500).json({ error: 'Error al iniciar sesión.' });
  }
});

// ============================================================
// GET /api/usuarios/perfil
// ============================================================
router.get('/perfil', verificarToken, (req, res) => {
  res.json(req.usuario);
});

// ============================================================
// GET /api/usuarios — listar usuarios (solo admin)
// ============================================================
router.get('/', verificarToken, requiereRol('admin'), async (req, res) => {
  try {
    const result = await pool.query(
      `SELECT id, nombre, usuario, rol, departamento, activo, creado_en, ultimo_acceso
       FROM usuarios ORDER BY nombre ASC`
    );
    res.json(result.rows);
  } catch (err) {
    res.status(500).json({ error: 'Error al obtener usuarios.' });
  }
});

// ============================================================
// POST /api/usuarios — crear usuario (solo admin)
// ============================================================
router.post('/', verificarToken, requiereRol('admin'), async (req, res) => {
  try {
    const { nombre, usuario, password, rol, departamento } = req.body;

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

    const result = await pool.query(
      `INSERT INTO usuarios (nombre, usuario, password_hash, rol, departamento)
       VALUES ($1, $2, $3, $4, $5) RETURNING id, nombre, usuario, rol, departamento`,
      [nombre, usuario.trim(), hash, rol, departamento]
    );

    res.status(201).json({ mensaje: 'Usuario creado correctamente.', usuario: result.rows[0] });
  } catch (err) {
    if (err.code === '23505') {
      return res.status(409).json({ error: 'Ya existe un usuario con ese nombre de usuario.' });
    }
    res.status(500).json({ error: 'Error al crear usuario.' });
  }
});

// ============================================================
// PUT /api/usuarios/:id — editar usuario (solo admin)
// ============================================================
router.put('/:id', verificarToken, requiereRol('admin'), async (req, res) => {
  try {
    const { id } = req.params;
    const { nombre, rol, departamento, activo, password } = req.body;

    let hashNuevo = null;
    if (password) {
      hashNuevo = await bcrypt.hash(password, 10);
    }

    await pool.query(`
      UPDATE usuarios SET
        nombre       = COALESCE($1, nombre),
        rol          = COALESCE($2, rol),
        departamento = COALESCE($3, departamento),
        activo       = COALESCE($4, activo),
        password_hash = COALESCE($5, password_hash)
      WHERE id = $6
    `, [nombre, rol, departamento, activo, hashNuevo, id]);

    res.json({ mensaje: 'Usuario actualizado correctamente.' });
  } catch (err) {
    res.status(500).json({ error: 'Error al actualizar usuario.' });
  }
});

module.exports = router;
