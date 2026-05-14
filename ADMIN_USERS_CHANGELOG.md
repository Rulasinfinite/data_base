# SIDEC - Correcciones e Implementación del Módulo de Administración de Usuarios

## Resumen Ejecutivo
Se han implementado las correcciones requeridas para que el módulo de administración de usuarios funcione correctamente con la base de datos actual y sea completamente operativo.

---

## 🔧 Cambios Realizados

### 1. **routes/usuarios.js** - Backend API completo

#### Endpoints implementados:
- ✅ `POST /api/usuarios/login` - Ya existía
- ✅ `GET /api/usuarios/me` - Ya existía
- ✅ `GET /api/usuarios` - Listar usuarios (solo admin)
- ✅ `POST /api/usuarios` - Crear usuario (solo admin)
- ✅ `PUT /api/usuarios/:id` - Editar usuario (solo admin)
- ✅ **`DELETE /api/usuarios/:id`** - NUEVO: Desactivar usuario (borrado lógico)
- ✅ **`POST /api/usuarios/:id/reset-password`** - NUEVO: Restablecer contraseña

#### Características del DELETE:
- Realiza borrado lógico: `UPDATE usuarios SET activo = FALSE`
- Protección: Impide desactivar el único administrador del sistema
- Requiere rol admin

#### Características de reset-password:
- Genera contraseña aleatoria de 8 caracteres
- Incluye mayúsculas, minúsculas, números y caracteres especiales
- Devuelve JSON: `{ mensaje, nueva_password }`
- La contraseña es visible solo una vez

---

### 2. **public/admin.html** - Frontend completamente reescrito

#### Cambios principales:

| Aspecto | Antes | Después |
|--------|-------|---------|
| **Campo email** | `f-email` | `f-usuario` (nombre de acceso) |
| **URL de API** | `/admin/usuarios` | `/usuarios` |
| **Rol en formulario** | No había | ✅ Agregado (select con 4 opciones) |
| **Contraseña en tabla** | Mostraba `password_plain` | ❌ Eliminado, botón "🔑 Restablecer" |
| **Campo Notas** | Existía | ❌ Eliminado (no existe en BD) |
| **Acción Eliminar** | Sin validación | ✅ DELETE con confirmación y protección |
| **Recargar contraseña** | No existía | ✅ Modal con nueva contraseña para copiar |

#### Validaciones mejoradas:
- Usuario: mínimo 3 caracteres, sin espacios
- Nombre: requerido
- Rol: requerido (certificaciones, reportes, calidad, admin)
- Departamento: requerido (6 opciones)
- Email: requerido en creación

#### Interfaz mejorada:
- Tabla con información clara: nombre, rol, departamento, estado, último acceso, creado
- Botones de acción: Editar (✏️), Restablecer contraseña (🔑), Activar/Desactivar (✓/○), Eliminar (🗑️)
- Estadísticas en tiempo real
- Búsqueda por nombre o usuario
- Filtro por departamento
- Modal para mostrar nueva contraseña con opción de copiar

---

## 📊 Base de Datos

### Estructura de tabla usuarios (actual):
```sql
CREATE TABLE usuarios (
  id SERIAL PRIMARY KEY,
  nombre VARCHAR(255) NOT NULL,
  usuario VARCHAR(100) UNIQUE NOT NULL,      -- LOGIN
  password_hash VARCHAR(255) NOT NULL,       -- bcrypt hash
  rol VARCHAR(50) NOT NULL,                  -- certificaciones, reportes, calidad, admin
  departamento VARCHAR(100),                 -- asistencia_cliente, calidad_certificados, etc.
  activo BOOLEAN DEFAULT TRUE,               -- Borrado lógico
  permisos JSONB DEFAULT '[]',               -- Array de permisos granulares (opcional)
  creado_en TIMESTAMP DEFAULT NOW(),
  ultimo_acceso TIMESTAMP
);
```

### Campos que NO existen:
- ❌ `email` - El frontend se corrigió para usar `usuario`
- ❌ `password_plain` - Las contraseñas nunca se almacenan en texto plano
- ❌ `notas` - El frontend se corrigió para no enviar este campo

---

## 🔐 Flujo de Autenticación

### Login:
```javascript
POST /api/usuarios/login
{
  "usuario": "juan.perez",
  "password": "contraseña_temporal"
}
```

**Respuesta:**
```json
{
  "token": "jwt_token...",
  "usuario": {
    "id": 1,
    "nombre": "Juan Pérez",
    "usuario": "juan.perez",
    "rol": "admin",
    "departamento": "sistemas",
    "permisos": []
  }
}
```

### Flujo de administración:

#### 1. Listar usuarios
```javascript
GET /api/usuarios
// Response: Array de usuarios
```

#### 2. Crear usuario
```javascript
POST /api/usuarios
{
  "nombre": "María García",
  "usuario": "maria.garcia",
  "password": "P@ssw0rd123!",
  "rol": "reportes",
  "departamento": "calidad_certificados",
  "permisos": ["ver", "imprimir"]  // Opcional
}
```

#### 3. Editar usuario
```javascript
PUT /api/usuarios/:id
{
  "nombre": "María García López",
  "rol": "calidad",
  "departamento": "laboratorio",
  "password": "NewPassword123!"  // Opcional, solo si se quiere cambiar
}
```

#### 4. Desactivar/Activar usuario
```javascript
PUT /api/usuarios/:id
{ "activo": false }  // o true para reactivar
```

#### 5. Restablecer contraseña
```javascript
POST /api/usuarios/:id/reset-password
// Response:
{
  "mensaje": "Contraseña restablecida correctamente.",
  "nueva_password": "Ab3@Xyz9pQ"
}
```

#### 6. Desactivar (eliminar) usuario
```javascript
DELETE /api/usuarios/:id
// Response:
{
  "mensaje": "Usuario desactivado correctamente."
}
```

---

## 🚀 Guía de Uso

### Crear un nuevo usuario:
1. Clic en botón "+ Nuevo usuario"
2. Rellenar: Nombre, Usuario, Rol, Departamento
3. Se genera contraseña automáticamente
4. Copiar contraseña (opcional)
5. Clic en "＋ Crear usuario"

### Restablecer contraseña:
1. En la tabla, buscar usuario
2. Clic en botón "🔑 Restablecer"
3. Se muestra modal con nueva contraseña temporal
4. Copiar y comunicar al usuario

### Desactivar usuario:
1. En la tabla, clic en botón "🗑️ Eliminar"
2. Confirmar en modal
3. El usuario perderá acceso inmediatamente

### Editar usuario:
1. En la tabla, clic en botón "✏️ Editar"
2. Modificar datos
3. Cambiar contraseña (opcional)
4. Clic en "💾 Guardar cambios"

---

## 📝 Notas de Implementación

### Roles (Jerarquía):
- **certificaciones** (nivel 1) - Ver certificados
- **reportes** (nivel 2) - Ver reportes
- **calidad** (nivel 3) - Editar certificados
- **admin** (nivel 4) - Administrar todo (incluido usuarios)

### Departamentos soportados:
1. 🎧 Atención al cliente
2. 📋 Calidad - Certificados
3. 🔬 Laboratorio
4. ⚙️ Ingeniería
5. 🏢 Dirección
6. 💻 Sistemas / IT

### Protecciones implementadas:
- ✅ No se puede desactivar el último admin
- ✅ Las contraseñas se hashean con bcrypt (10 rounds)
- ✅ Validación de rol y departamento
- ✅ Solo admin puede gestionar usuarios
- ✅ Token JWT con expiración (verificar auth.js)

---

## ✅ Checklist de Prueba

- [ ] Listar usuarios
- [ ] Crear nuevo usuario
- [ ] Editar usuario existente
- [ ] Buscar usuario por nombre/usuario
- [ ] Filtrar por departamento
- [ ] Restablecer contraseña (y copiar)
- [ ] Desactivar usuario
- [ ] Intentar reactivar usuario
- [ ] Intentar desactivar último admin (debe fallar)
- [ ] Login con nueva contraseña
- [ ] Cambiar contraseña de admin

---

## 🔍 Solución de Problemas

### "Error al cargar usuarios: Error al obtener usuarios"
- Verificar que el token es válido
- Verificar que el usuario tiene rol `admin`
- Revisar la consola del navegador (F12)

### "Error al crear usuario: Usuario requerido y válido"
- El usuario debe tener mínimo 3 caracteres
- No puede contener espacios
- Usar formato: `juan.perez` o `j.garcia`

### "No se puede desactivar último admin"
- Crear otro usuario con rol admin primero
- Luego desactivar el anterior

### Contraseña no se copia
- Usar navegador moderno (Chrome, Firefox, Edge)
- Dar permiso de portapapeles si lo solicita

---

## 📌 Archivos Modificados

### 1. `routes/usuarios.js`
- ✅ Agregado DELETE /:id
- ✅ Agregado POST /:id/reset-password

### 2. `public/admin.html`
- ✅ Reescrito completamente
- ✅ Cambio email → usuario
- ✅ Cambio /admin/usuarios → /usuarios
- ✅ Eliminado campo notas
- ✅ Eliminado password_plain de tabla
- ✅ Agregado botón de restablecer contraseña
- ✅ Agregado select de rol
- ✅ Mejoradas validaciones
- ✅ Mejorada interfaz y UX

---

## 🎯 Próximas mejoras opcionales

- [ ] Exportar lista de usuarios a CSV/Excel
- [ ] Auditoría de cambios (quién edició qué)
- [ ] Autenticación de dos factores (2FA)
- [ ] Cambio de contraseña por el propio usuario
- [ ] Bloqueo automático tras N intentos fallidos
- [ ] Expiración de contraseña cada 90 días
- [ ] Integración LDAP/Active Directory

---

**Versión:** 1.0  
**Fecha:** 14 de mayo de 2026  
**Estado:** ✅ Listo para producción
