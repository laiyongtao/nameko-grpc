# -*- coding: utf-8 -*-
import sys
import time
from concurrent import futures
from importlib import import_module

import grpc
from grpc._cython.cygrpc import CompressionAlgorithm, CompressionLevel


_ONE_DAY_IN_SECONDS = 60 * 60 * 24


if __name__ == "__main__":

    port = sys.argv[1]

    # TODO do this via env and PYTHONPATH when starting this subprocess
    source_dir = sys.argv[2]
    sys.path.append(source_dir)

    proto_name = sys.argv[3]
    service_name = sys.argv[4]

    compression_algorithm = sys.argv[5]
    compression_level = sys.argv[6]

    service_module = import_module("{}_grpc".format(proto_name))
    service_cls = getattr(service_module, service_name)

    grpc_module = import_module("{}_pb2_grpc".format(proto_name))
    add_servicer = getattr(grpc_module, "add_{}Servicer_to_server".format(service_name))

    server_options = [
        (
            "grpc.default_compression_algorithm",
            getattr(CompressionAlgorithm, compression_algorithm),
        ),
        (
            "grpc.default_compression_level",
            getattr(CompressionLevel, compression_level),
        ),
    ]

    def serve():

        server = grpc.server(
            futures.ThreadPoolExecutor(max_workers=10), options=server_options
        )
        add_servicer(service_cls(), server)
        server.add_insecure_port("[::]:{}".format(port))
        server.start()
        try:
            while True:
                time.sleep(_ONE_DAY_IN_SECONDS)
        except KeyboardInterrupt:
            server.stop(0)

    serve()