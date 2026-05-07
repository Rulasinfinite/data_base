-- ============================================================
-- SIDEC - Sistema de Certificados de Calibración
-- Base de datos: sidec_db | Server: sidecmexico
-- Schema principal (sin particionamiento, con UNIQUE en numero_informe)
-- ============================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================
-- TABLA: tipos_magnitud
-- ============================================================
CREATE TABLE IF NOT EXISTS tipos_magnitud (
    id          SERIAL PRIMARY KEY,
    nombre      VARCHAR(100) NOT NULL UNIQUE,
    descripcion TEXT
);

INSERT INTO tipos_magnitud (nombre) VALUES
    ('DIMENSIONAL'),('ELÉCTRICA'),('MASA'),('TEMPERATURA Y HUMEDAD'),
    ('PRESIÓN'),('FUERZA'),('VOLUMEN'),('PAR TORSIONAL'),
    ('TIEMPO Y FRECUENCIA'),('QUÍMICA'),('FLUJO'),('ACELERACIÓN'),
    ('DENSIDAD')
ON CONFLICT (nombre) DO NOTHING;

-- ============================================================
-- TABLA: certificados (versión unificada)
-- ============================================================
CREATE TABLE IF NOT EXISTS certificados (
    id                      BIGSERIAL PRIMARY KEY,
    numero_informe          VARCHAR(50)  NOT NULL UNIQUE,
    anio_emision            SMALLINT     NOT NULL,
    nombre_cliente          VARCHAR(255),
    direccion               TEXT,
    atencion_a              VARCHAR(255),
    descripcion_instrumento VARCHAR(255),
    alcance                 TEXT,
    numero_serie            VARCHAR(100),
    identificacion          VARCHAR(100),
    modelo                  VARCHAR(100),
    marca                   VARCHAR(100),
    magnitud_evaluada       VARCHAR(100),
    resultado_calibracion   TEXT,
    incertidumbre           TEXT,
    temperatura             VARCHAR(50),
    humedad_relativa        VARCHAR(50),
    fecha_recepcion         DATE,
    fecha_calibracion       DATE,
    fecha_emision           DATE,
    metodo_utilizado        TEXT,
    lugar_calibracion       VARCHAR(255),
    calibrado_por           VARCHAR(255),
    aprobado_por            VARCHAR(255),
    ruta_archivo_origen     TEXT,
    fecha_importacion       TIMESTAMPTZ DEFAULT NOW(),
    importado_por           VARCHAR(100),
    activo                  BOOLEAN DEFAULT TRUE
);

-- ============================================================
-- ÍNDICES
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_cert_numero_informe
    ON certificados (numero_informe);

CREATE INDEX IF NOT EXISTS idx_cert_cliente_trgm
    ON certificados USING GIN (nombre_cliente gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_cert_numero_serie
    ON certificados (numero_serie);

CREATE INDEX IF NOT EXISTS idx_cert_identificacion
    ON certificados (identificacion);

CREATE INDEX IF NOT EXISTS idx_cert_fecha_emision
    ON certificados (fecha_emision);

CREATE INDEX IF NOT EXISTS idx_cert_anio
    ON certificados (anio_emision);

CREATE INDEX IF NOT EXISTS idx_cert_marca_trgm
    ON certificados USING GIN (marca gin_trgm_ops);

-- ============================================================
-- TABLA: usuarios (sin cambios)
-- ============================================================
CREATE TABLE IF NOT EXISTS usuarios (
    id              SERIAL PRIMARY KEY,
    nombre          VARCHAR(150) NOT NULL,
    usuario         VARCHAR(50)  NOT NULL UNIQUE,
    password_hash   VARCHAR(255) NOT NULL,
    rol             VARCHAR(50)  NOT NULL DEFAULT 'certificaciones',
    departamento    VARCHAR(100),
    activo          BOOLEAN DEFAULT TRUE,
    creado_en       TIMESTAMPTZ DEFAULT NOW(),
    ultimo_acceso   TIMESTAMPTZ
);

-- ============================================================
-- TABLA: auditoria
-- ============================================================
CREATE TABLE IF NOT EXISTS auditoria (
    id          BIGSERIAL PRIMARY KEY,
    usuario_id  INTEGER REFERENCES usuarios(id),
    accion      VARCHAR(50) NOT NULL,
    tabla       VARCHAR(50),
    registro_id BIGINT,
    datos_antes JSONB,
    datos_despues JSONB,
    ip_origen   VARCHAR(45),
    creado_en   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_auditoria_usuario ON auditoria (usuario_id);
CREATE INDEX IF NOT EXISTS idx_auditoria_fecha   ON auditoria (creado_en);

-- ============================================================
-- TABLA: importaciones
-- ============================================================
CREATE TABLE IF NOT EXISTS importaciones (
    id              SERIAL PRIMARY KEY,
    usuario_id      INTEGER REFERENCES usuarios(id),
    carpeta_origen  TEXT,
    total_archivos  INTEGER DEFAULT 0,
    exitosos        INTEGER DEFAULT 0,
    fallidos        INTEGER DEFAULT 0,
    omitidos        INTEGER DEFAULT 0,
    errores         JSONB,
    iniciado_en     TIMESTAMPTZ DEFAULT NOW(),
    finalizado_en   TIMESTAMPTZ,
    estado          VARCHAR(20) DEFAULT 'en_proceso'
);

-- ============================================================
-- USUARIOS ADMIN
-- ============================================================
INSERT INTO usuarios (nombre, usuario, password_hash, rol, departamento)
VALUES (
    'Administrador App SIDEC',
    'Adminappsidec',
    '$2b$10$noUwyXbAGn04LMmNccrw6.tp8FKzjSB/U68T68cDug6Rg/VYPqpIq',
    'admin', 'Administración'
) ON CONFLICT (usuario) DO UPDATE
    SET password_hash = EXCLUDED.password_hash,
        rol           = 'admin',
        activo        = TRUE;

INSERT INTO usuarios (nombre, usuario, password_hash, rol, departamento)
VALUES (
    'Administrador SIDEC',
    'Administrador_Sidec',
    '$2b$10$noUwyXbAGn04LMmNccrw6.tp8FKzjSB/U68T68cDug6Rg/VYPqpIq',
    'admin', 'Administración'
) ON CONFLICT (usuario) DO UPDATE
    SET password_hash = EXCLUDED.password_hash,
        rol           = 'admin',
        activo        = TRUE;

-- ============================================================
-- VISTA: resumen por año
-- ============================================================
CREATE OR REPLACE VIEW resumen_por_anio AS
SELECT
    anio_emision,
    COUNT(*)                       AS total_certificados,
    COUNT(DISTINCT nombre_cliente) AS total_clientes,
    COUNT(DISTINCT marca)          AS total_marcas,
    MIN(fecha_emision)             AS primera_emision,
    MAX(fecha_emision)             AS ultima_emision
FROM certificados
WHERE activo = TRUE
GROUP BY anio_emision
ORDER BY anio_emision DESC;