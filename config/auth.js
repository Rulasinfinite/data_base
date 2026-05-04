// config/auth.js
// JWT + control de roles por departamento

const jwt = require('jsonwebtoken');

const JWT_SECRET = process.env.JWT_SECRET || 'sidec_secret_cambiar_en_produccion';
const JWT_EXPIRES = '8h'; // sesión de 8 horas laborales

// Jerarquía de permisos (mayor número = más acceso)
const NIVEL_ROL = {
  certificaciones: 1,
  reportes:        2,
  calidad:         3,
  admin:           4,
};

// Generar token al hacer login
function generarToken(usuario) {
  return jwt.sign(
    {
      id:           usuario.id,
      usuario:      usuario.usuario,
      nombre:       usuario.nombre,
      rol:          usuario.rol,
      departamento: usuario.departamento,
    },
    JWT_SECRET,
    { expiresIn: JWT_EXPIRES }
  );
}

// Middleware: verificar que el usuario tiene sesión activa
function verificarToken(req, res, next) {
  const auth = req.headers['authorization'];
  const token = auth && auth.startsWith('Bearer ') ? auth.slice(7) : null;

  if (!token) {
    return res.status(401).json({ error: 'Sesión requerida. Por favor inicia sesión.' });
  }

  try {
    const decoded = jwt.verify(token, JWT_SECRET);
    req.usuario = decoded;
    next();
  } catch (err) {
    return res.status(401).json({ error: 'Sesión expirada o inválida. Inicia sesión nuevamente.' });
  }
}

// Middleware: verificar que el usuario tiene el rol mínimo requerido
function requiereRol(rolMinimo) {
  return (req, res, next) => {
    const nivelUsuario  = NIVEL_ROL[req.usuario?.rol] || 0;
    const nivelRequerido = NIVEL_ROL[rolMinimo] || 99;

    if (nivelUsuario < nivelRequerido) {
      return res.status(403).json({
        error: `Acceso denegado. Se requiere rol: ${rolMinimo}.`,
      });
    }
    next();
  };
}

// Roles disponibles en el sistema
const ROLES = Object.keys(NIVEL_ROL);

module.exports = { generarToken, verificarToken, requiereRol, ROLES };
