-- Esquema base (MySQL/MariaDB)
CREATE DATABASE IF NOT EXISTS sistema_contable;
USE sistema_contable;

-- Usuarios y Empresas
CREATE TABLE IF NOT EXISTS usuarios (
  id INT PRIMARY KEY AUTO_INCREMENT,
  nombre VARCHAR(100) NOT NULL,
  correo VARCHAR(100) NOT NULL UNIQUE,
  contrasena_hash VARCHAR(255),                 -- si luego agregas login tradicional
  rol ENUM('docente','empleado','dueno') NOT NULL DEFAULT 'empleado',
  google_sub VARCHAR(255) UNIQUE                -- ID estable de Google OAuth
);

CREATE TABLE IF NOT EXISTS empresas (
  id_empresa INT PRIMARY KEY AUTO_INCREMENT,
  nombre VARCHAR(100) NOT NULL UNIQUE,
  descripcion TEXT,
  id_gerente INT UNIQUE,                        -- dueño (1:1)
  CONSTRAINT fk_empresas_dueno FOREIGN KEY (id_gerente) REFERENCES usuarios(id)
    ON UPDATE CASCADE ON DELETE SET NULL
);

-- Afiliaciones de empleados a empresa (1 empresa por empleado)
CREATE TABLE IF NOT EXISTS empresa_empleados (
  id_empresa INT NOT NULL,
  id_usuario INT NOT NULL UNIQUE,               -- un empleado no puede estar en 2 empresas
  PRIMARY KEY (id_empresa, id_usuario),
  CONSTRAINT fk_ee_emp FOREIGN KEY (id_empresa) REFERENCES empresas(id_empresa)
    ON UPDATE CASCADE ON DELETE CASCADE,
  CONSTRAINT fk_ee_usr FOREIGN KEY (id_usuario) REFERENCES usuarios(id)
    ON UPDATE CASCADE ON DELETE CASCADE
);

-- PLAN DE CUENTAS por empresa (clonado desde plantilla)
CREATE TABLE IF NOT EXISTS plan_cuentas (
  id_cuenta INT PRIMARY KEY AUTO_INCREMENT,
  id_empresa INT NOT NULL,
  cod_rubro VARCHAR(50),
  rubro VARCHAR(100),
  cod_subrubro VARCHAR(50),
  subrubro VARCHAR(100),
  cuenta VARCHAR(100),
  CONSTRAINT fk_pc_emp FOREIGN KEY (id_empresa) REFERENCES empresas(id_empresa)
    ON UPDATE CASCADE ON DELETE CASCADE
);

-- Plantilla global (opcional) para clonado inicial
CREATE TABLE IF NOT EXISTS plan_cuentas_plantilla (
  id_tpl INT PRIMARY KEY AUTO_INCREMENT,
  cod_rubro VARCHAR(50),
  rubro VARCHAR(100),
  cod_subrubro VARCHAR(50),
  subrubro VARCHAR(100),
  cuenta VARCHAR(100)
);

-- Transacciones (si las usas fuera del asiento)
CREATE TABLE IF NOT EXISTS transacciones (
  id_transaccion INT PRIMARY KEY AUTO_INCREMENT,
  id_empresa INT NOT NULL,
  tipo ENUM('ingreso','egreso'),
  doc_respaldatorio VARCHAR(100),
  fecha DATE,
  contacto VARCHAR(100),
  importe DECIMAL(12,2),
  condicion VARCHAR(100),
  CONSTRAINT fk_tr_emp FOREIGN KEY (id_empresa) REFERENCES empresas(id_empresa)
    ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS asientos_diarios (
  id_asiento INT PRIMARY KEY AUTO_INCREMENT,
  id_empresa INT NOT NULL,
  fecha DATE NOT NULL,
  num_asiento INT NOT NULL,                     -- correlativo por empresa
  doc_respaldatorio VARCHAR(100),
  datos_adjuntos TEXT,
  id_usuario INT,                               -- quien lo cargó
  leyenda TEXT,
  CONSTRAINT uq_asiento_empresa UNIQUE (id_empresa, num_asiento),
  CONSTRAINT fk_ad_emp FOREIGN KEY (id_empresa) REFERENCES empresas(id_empresa)
    ON UPDATE CASCADE ON DELETE CASCADE,
  CONSTRAINT fk_ad_usr FOREIGN KEY (id_usuario) REFERENCES usuarios(id)
    ON DELETE SET NULL ON UPDATE CASCADE
);

CREATE TABLE IF NOT EXISTS detalle_asiento (
  id_detalle INT PRIMARY KEY AUTO_INCREMENT,
  id_asiento INT NOT NULL,
  id_cuenta INT NOT NULL,
  tipo ENUM('debe','haber') NOT NULL,
  importe DECIMAL(12,2) NOT NULL CHECK (importe >= 0),
  CONSTRAINT fk_da_asiento FOREIGN KEY (id_asiento) REFERENCES asientos_diarios(id_asiento)
    ON UPDATE CASCADE ON DELETE CASCADE,
  CONSTRAINT fk_da_cuenta FOREIGN KEY (id_cuenta) REFERENCES plan_cuentas(id_cuenta)
    ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS mayor_cuentas (
  id_mayor INT PRIMARY KEY AUTO_INCREMENT,
  id_empresa INT NOT NULL,
  id_cuenta INT NOT NULL,
  fecha DATE,
  num_asiento INT,
  debe DECIMAL(12,2) DEFAULT 0,
  haber DECIMAL(12,2) DEFAULT 0,
  saldo DECIMAL(12,2),
  CONSTRAINT fk_may_emp FOREIGN KEY (id_empresa) REFERENCES empresas(id_empresa)
    ON UPDATE CASCADE ON DELETE CASCADE,
  CONSTRAINT fk_may_cuenta FOREIGN KEY (id_cuenta) REFERENCES plan_cuentas(id_cuenta)
    ON UPDATE CASCADE ON DELETE RESTRICT
);

-- Estados (todos scoping por empresa)
CREATE TABLE IF NOT EXISTS estado_situacion_patrimonial (
  id_estado INT PRIMARY KEY AUTO_INCREMENT,
  id_empresa INT NOT NULL,
  cod_rubro VARCHAR(50),
  rubro VARCHAR(100),
  cod_subrubro VARCHAR(50),
  subrubro VARCHAR(100),
  importe DECIMAL(12,2),
  CONSTRAINT fk_esp_emp FOREIGN KEY (id_empresa) REFERENCES empresas(id_empresa)
    ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS estado_resultados (
  id_resultado INT PRIMARY KEY AUTO_INCREMENT,
  id_empresa INT NOT NULL,
  cod_rubro VARCHAR(50),
  rubro VARCHAR(100),
  cod_subrubro VARCHAR(50),
  subrubro VARCHAR(100),
  cuenta VARCHAR(100),
  saldo DECIMAL(12,2),
  CONSTRAINT fk_er_emp FOREIGN KEY (id_empresa) REFERENCES empresas(id_empresa)
    ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS estado_fondos (
  id_fondo INT PRIMARY KEY AUTO_INCREMENT,
  id_empresa INT NOT NULL,
  cod_rubro VARCHAR(50),
  rubro VARCHAR(100),
  cod_subrubro VARCHAR(50),
  subrubro VARCHAR(100),
  cuenta VARCHAR(100),
  importe DECIMAL(12,2),
  CONSTRAINT fk_ef_emp FOREIGN KEY (id_empresa) REFERENCES empresas(id_empresa)
    ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS analisis_indices (
  id_indice INT PRIMARY KEY AUTO_INCREMENT,
  id_empresa INT NOT NULL,
  activos_corrientes DECIMAL(12,2),
  pasivos_corrientes DECIMAL(12,2),
  indice_de_liquidez DECIMAL(12,4),
  saldos_activos DECIMAL(12,2),
  saldos_pasivos DECIMAL(12,2),
  indice_de_solvencia DECIMAL(12,4),
  saldo_de_pasivo DECIMAL(12,2),
  saldo_pn DECIMAL(12,2),
  indice_de_endeudamiento DECIMAL(12,4),
  costo_mercancias_vendidas DECIMAL(12,2),
  ventas DECIMAL(12,2),
  indice_costo_ventas DECIMAL(12,4),
  utilidad_del_ejercicio DECIMAL(12,2),
  patrimonio_neto DECIMAL(12,2),
  indice_retorno_inversion DECIMAL(12,4),
  CONSTRAINT fk_ai_emp FOREIGN KEY (id_empresa) REFERENCES empresas(id_empresa)
    ON UPDATE CASCADE ON DELETE CASCADE
);

--SEMILLAS (IMPORTANTES)
USE sistema_contable;

INSERT INTO plan_cuentas_plantilla (cod_rubro, rubro, cod_subrubro, subrubro, cuenta) VALUES
('1','ACTIVO','1.1','ACTIVO CORRIENTE','CAJA'),
('1','ACTIVO','1.1','ACTIVO CORRIENTE','BANCOS'),
('1','ACTIVO','1.2','ACTIVO NO CORRIENTE','MOBILIARIO'),
('2','PASIVO','2.1','PASIVO CORRIENTE','PROVEEDORES'),
('3','PATRIMONIO','3.1','PATRIMONIO NETO','CAPITAL'),
('4','RESULTADO','4.1','INGRESOS','VENTAS'),
('5','RESULTADO','5.1','EGRESOS','COSTO DE VENTAS');
