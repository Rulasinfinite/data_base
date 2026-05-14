// routes/usuarios.js
const express = require('express');
const router = express.Router();
const bcrypt = require('bcrypt');
const pool = require('../config/db');
const { generarToken, verificarToken, requiereRol, ROLES } = require('../config/auth');

// POST /api/usuarios/login
router.post('/login', async (req, res) => {
  try {
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

// DELETE /api/usuarios/:id (eliminar - desactivar lógicamente)
router.delete('/:id', verificarToken, requiereRol('admin'), async (req, res) => {
  try {
    const { id } = req.params;
    
    // Verificar que no es el último admin
    const adminCount = await pool.query(
      'SELECT COUNT(*) as total FROM usuarios WHERE rol = $1 AND activo = TRUE',
      ['admin']
    );
    
    if (parseInt(adminCount.rows[0].total) === 1) {
      // Verificar si el usuario a eliminar es admin
      const usuario = await pool.query('SELECT rol FROM usuarios WHERE id = $1', [id]);
      if (usuario.rows.length > 0 && usuario.rows[0].rol === 'admin') {
        return res.status(400).json({ error: 'No puede eliminar el único administrador del sistema.' });
      }
    }
    
    await pool.query(
      'UPDATE usuarios SET activo = FALSE WHERE id = $1',
      [id]
    );
    res.json({ mensaje: 'Usuario desactivado correctamente.' });
  } catch (err) {
    res.status(500).json({ error: 'Error al eliminar usuario.' });
  }
});

// POST /api/usuarios/:id/reset-password (restablecer contraseña)
router.post('/:id/reset-password', verificarToken, requiereRol('admin'), async (req, res) => {
  try {
    const { id } = req.params;
    
    // Generar nueva contraseña aleatoria
    const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789@#$!';
    let newPassword = '';
    while (newPassword.length < 8) {
      newPassword += chars[Math.floor(Math.random() * chars.length)];
    }
    
    // Hashear y actualizar
    const hash = await bcrypt.hash(newPassword, 10);
    await pool.query(
      'UPDATE usuarios SET password_hash = $1 WHERE id = $2',
      [hash, id]
    );
    
    res.json({
      mensaje: 'Contraseña restablecida correctamente.',
      nueva_password: newPassword
    });
  } catch (err) {
    res.status(500).json({ error: 'Error al restablecer contraseña.' });
  }
});

module.exports = router;