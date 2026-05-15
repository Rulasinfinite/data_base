-- ============================================================
-- SIDEC - Sistema de Certificados de Calibración
-- Base de datos: sidec_db | Server: sidecmexico
-- Schema con clientes normalizados, archivos adjuntos,
-- estado del certificado y fecha de vencimiento manual.
-- MODIFICADO: se ampliaron longitudes de columnas para evitar
-- errores "valor demasiado largo para tipo character varying".
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
-- TABLA: clientes (normalizada)
-- ============================================================
CREATE TABLE IF NOT EXISTS clientes (
    id          SERIAL PRIMARY KEY,
    nombre      VARCHAR(255) NOT NULL UNIQUE,
    direccion   TEXT,
    atencion_a  VARCHAR(255)
);

-- ============================================================
-- TABLA: certificados
-- ============================================================
CREATE TABLE IF NOT EXISTS certificados (
    id                      BIGSERIAL PRIMARY KEY,
    numero_informe          VARCHAR(100) NOT NULL,   -- 50 -> 100
    anio_emision            SMALLINT     NOT NULL,
    cliente_id              INTEGER REFERENCES clientes(id),
    descripcion_instrumento TEXT,                    -- VARCHAR(255) -> TEXT
    alcance                 TEXT,
    numero_serie            VARCHAR(200),            -- 100 -> 200
    identificacion          VARCHAR(200),            -- 100 -> 200
    modelo                  VARCHAR(200),            -- 100 -> 200
    marca                   VARCHAR(200),            -- 100 -> 200
    magnitud_evaluada       VARCHAR(200),            -- 100 -> 200
    resultado_calibracion   TEXT,
    incertidumbre           TEXT,
    temperatura             VARCHAR(200),            -- 50 -> 200
    humedad_relativa        VARCHAR(200),            -- 50 -> 200
    fecha_recepcion         DATE,
    fecha_calibracion       DATE,
    fecha_emision           DATE,
    fecha_vencimiento       DATE,
    estado                  VARCHAR(20) DEFAULT 'vigente'
                            CHECK (estado IN ('vigente','anulado','provisional','vencido')),
    metodo_utilizado        TEXT,
    lugar_calibracion       TEXT,                    -- VARCHAR(255) -> TEXT
    calibrado_por           VARCHAR(255),
    aprobado_por            VARCHAR(255),
    ruta_archivo_origen     TEXT,
    fecha_importacion       TIMESTAMPTZ DEFAULT NOW(),
    importado_por           VARCHAR(100),
    activo                  BOOLEAN DEFAULT TRUE,
    -- Evitar duplicados exactos de mismo informe + cliente + marca
    CONSTRAINT unique_certificado UNIQUE (numero_informe, cliente_id, marca)
);

-- ============================================================
-- ÍNDICES
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_cert_numero_informe
    ON certificados (numero_informe);

CREATE INDEX IF NOT EXISTS idx_cert_cliente_id
    ON certificados (cliente_id);

CREATE INDEX IF NOT EXISTS idx_cert_numero_serie
    ON certificados (numero_serie);

CREATE INDEX IF NOT EXISTS idx_cert_identificacion
    ON certificados (identificacion);

CREATE INDEX IF NOT EXISTS idx_cert_fecha_emision
    ON certificados (fecha_emision);

CREATE INDEX IF NOT EXISTS idx_cert_anio
    ON certificados (anio_emision);

CREATE INDEX IF NOT EXISTS idx_cert_estado
    ON certificados (estado);

-- Índice de texto sobre nombre de cliente (ahora en tabla clientes)
CREATE INDEX IF NOT EXISTS idx_clientes_trgm
    ON clientes USING GIN (nombre gin_trgm_ops);

-- ============================================================
-- TABLA: archivos_adjuntos
-- ============================================================
CREATE TABLE IF NOT EXISTS archivos_adjuntos (
    id              SERIAL PRIMARY KEY,
    certificado_id  BIGINT REFERENCES certificados(id) ON DELETE CASCADE,
    nombre_original VARCHAR(500),
    ruta_archivo    TEXT NOT NULL,
    fecha_subida    TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_adjuntos_certificado
    ON archivos_adjuntos (certificado_id);

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
-- TABLA: notas (apuntes de usuarios)
-- ============================================================
CREATE TABLE IF NOT EXISTS notas (
    id          SERIAL PRIMARY KEY,
    usuario_id  INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
    titulo      VARCHAR(255) NOT NULL,
    contenido   TEXT,
    creada_en   TIMESTAMPTZ DEFAULT NOW(),
    actualizada_en TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notas_usuario ON notas (usuario_id);

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
    c.anio_emision,
    COUNT(*)                          AS total_certificados,
    COUNT(DISTINCT cl.nombre)         AS total_clientes,
    COUNT(DISTINCT c.marca)           AS total_marcas,
    MIN(c.fecha_emision)              AS primera_emision,
    MAX(c.fecha_emision)              AS ultima_emision
FROM certificados c
JOIN clientes cl ON cl.id = c.cliente_id
WHERE c.activo = TRUE
GROUP BY c.anio_emision
ORDER BY c.anio_emision DESC;