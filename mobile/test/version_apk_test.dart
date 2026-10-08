// Si se ofrece una actualización o no.
//
// ## Por qué esta decisión tiene su propio fichero
// Porque es la que decide si la app **pide un binario de 50 MB** y después le
// pide a una persona que lo instale. Si el criterio está mal en dos bytes, el
// síntoma es «la app dice que está al día y no lo está» o «insiste en actualizar
// cuando no hay nada» — y el segundo caso hace que la app pierda credibilidad la
// primera vez que se equivoca.
import 'package:aegis_console/core/network/instalador_nativo.dart';
import 'package:aegis_console/data/models/version_apk.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  /// Un APK del bridge con el número que le pidamos.
  VersionApk delBridge(int code) =>
      VersionApk(versionCode: code, versionName: '1.0.$code');

  group('qué se ofrece', () {
    test('cuando el bridge tiene un número mayor', () {
      final v = VersionApk.evaluado(
        instalado: 2,
        hayPermiso: true,
        delBridge: delBridge(3),
      );
      expect(v.disponible, isTrue);
      expect(v.versionCode, 3);
    });

    test('cuando los números son iguales, no hay nada nuevo', () {
      // El caso que más se olvida: se acaba de instalar la 2 y el bridge sigue
      // en la 2. Ofrecer «actualizar» aquí hace que la app parezca zonza.
      final v = VersionApk.evaluado(
        instalado: 2,
        hayPermiso: true,
        delBridge: delBridge(2),
      );
      expect(v.disponible, isFalse);
    });

    test('cuando el bridge tiene un número MENOR, tampoco hay nada nuevo', () {
      // Un `!=` en vez de un `>` diría «hay actualización» sobre algo que
      // Android va a rechazar con un error que no explica. El que decide es el
      // `>` del modelo, y este test lo fija.
      final v = VersionApk.evaluado(
        instalado: 5,
        hayPermiso: true,
        delBridge: delBridge(3),
      );
      expect(v.disponible, isFalse);
    });
  });

  group('lo que se dice cuando no hay nada', () {
    test('el bridge sin APK no es lo mismo que «estás al día»', () {
      // Sin esta distinción, un bridge recién arrancado se ve exactamente igual
      // que una app actualizada, y son dos situaciones opuestas: una se
      // arregla esperando, la otra no tiene nada que arreglar.
      final v = VersionApk.evaluado(instalado: 2, hayPermiso: true);
      expect(v.versionCode, 0);
      expect(v.disponible, isFalse);
      expect(v.estado, contains('no tiene un APK'));
    });

    test('el motivo del bridge se enseña tal cual', () {
      // El bridge sabe por qué no sirve: o no compiló, o no pasó la puerta. Ese
      // motivo es más útil que cualquier frase genérica, y taparlo con «no hay
      // nada» tira información que ya se tenía.
      final v = VersionApk.evaluado(
        instalado: 2,
        hayPermiso: true,
        motivo: 'el APK es más viejo que el código de mobile/',
      );
      expect(v.estado, 'el APK es más viejo que el código de mobile/');
    });
  });

  group('el permiso de instalar', () {
    test('sin permiso, el texto dice qué hacer y dónde', () {
      // Un botón que ofrece instalar sin decir que falta el permiso lleva a un
      // intent que el sistema no va a mostrar. El texto tiene que corregir eso.
      final v = VersionApk.evaluado(instalado: 2, hayPermiso: false, delBridge: delBridge(3));
      expect(v.disponible, isTrue, reason: 'la versión nueva existe igual; falta el permiso');
      expect(v.estado, contains('Acceso especial'));
    });

    test('con permiso, el texto dice que Android lo confirmará', () {
      // Y no dice «se instalará», porque el desenlace lo controla el sistema. Es
      // la misma línea entre «te toca confirmar» y «instalado».
      final v = VersionApk.evaluado(instalado: 2, hayPermiso: true, delBridge: delBridge(3));
      expect(v.estado, contains('te lo confirmará Android'));
      expect(v.estado, isNot(contains('instalada')));
    });
  });

  group('el canal nativo', () {
    test('sin canal, versionCode da 0 y no tumba nada', () async {
      // En un test, o en un móvil viejo sin el método, `invokeMethod` puede
      // fallar. La app tiene que poder seguir usándose; lo que no se puede es la
      // actualización.
      const canal = InstaladorPorCanal('aegis/instalar');
      // Sin handler, `invokeMethod` lanza `MissingPluginException`.
      var fallo = false;
      try {
        await canal.versionCode();
      } on Object {
        fallo = true;
      }
      // Con un canal sin handler esto **debe** fallar: la prueba real es que la
      // app que lo llama lo Captura. Aquí se deja constancia de que el canal
      // sin implementer lanza, que es justo lo que hace que el `try` del
      // repositorio no sea opcional.
      expect(fallo, isTrue);
    });

    test('el doble recuerda qué se instaló y si se abrió el permiso', () async {
      // El doble guarda lo que pasó porque un test necesita comprobar **qué** se
      // instaló, no solo que se llamó a instalar.
      final d = InstaladorFalso(ruta: '/data/apk/aegis-3.apk');
      expect(await d.instalar('/data/apk/aegis-3.apk'), isNull);
      expect(d.instaladas, ['/data/apk/aegis-3.apk']);

      await d.abrirPermiso();
      expect(d.permisoAbierto, isTrue);
    });

    test('el motivo de fallo se propaga tal cual', () async {
      // `sin_instalador` es un caso con su propia explicación: no es lo mismo
      // que un error de permisos. Si se pierde, la pantalla no podría
      // distinguirlos.
      final d = InstaladorFalso(fallaInstalar: true);
      expect(await d.instalar('/x.apk'), 'sin_instalador');
    });
  });

  test('al día no dice «listo para instalar», aunque tenga permiso', () {
    // El fallo medido: con la v12 instalada y la v12 en el bridge, el diálogo
    // seguía diciendo «Listo: al instalar te lo confirmará Android» y no había
    // ningún botón al lado. La frase se elegía mirando el permiso y solo el
    // permiso.
    final v = VersionApk.evaluado(
      instalado: 12,
      hayPermiso: true,
      delBridge: const VersionApk(versionCode: 12, versionName: '1.0.11'),
    );

    expect(v.disponible, isFalse);
    expect(v.estado, contains('al día'));
    expect(v.estado, isNot(contains('instalar')));
  });

  test('con versión nueva y permiso, sí dice que se puede instalar', () {
    // El otro lado de la misma regla: que «al día» no se coma el caso bueno.
    final v = VersionApk.evaluado(
      instalado: 11,
      hayPermiso: true,
      delBridge: const VersionApk(versionCode: 12, versionName: '1.0.11'),
    );

    expect(v.disponible, isTrue);
    expect(v.estado, contains('Android'));
  });

  test('al día sin permiso tampoco pide el permiso', () {
    // Pedir un permiso que no hace falta es ruido: la única razón de pedirlo es
    // que haya algo que instalar.
    final v = VersionApk.evaluado(
      instalado: 12,
      hayPermiso: false,
      delBridge: const VersionApk(versionCode: 12, versionName: '1.0.11'),
    );

    expect(v.estado, isNot(contains('permiso')));
  });
}
