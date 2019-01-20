# -*- coding: utf-8 -*-
""" Test integration with https://github.com/nameko/nameko-tracer
"""

import logging

import pytest
from grpc import StatusCode
from nameko_tracer.constants import Stage

from nameko_grpc.constants import Cardinality
from nameko_grpc.exceptions import GrpcError


@pytest.mark.usefixtures("predictable_call_ids")
class TestTracerIntegration:
    @pytest.fixture
    def client_type(self):
        return "nameko"  # no point testing multiple clients

    @pytest.fixture
    def server(self, start_nameko_server):
        return start_nameko_server("tracer")

    @pytest.fixture
    def caplog(self, caplog):
        with caplog.at_level(logging.INFO):
            yield caplog

    @pytest.fixture
    def get_log_records(self, caplog):
        def is_trace(record):
            return record.name == "nameko_tracer"

        def is_request(record):
            return record.stage == Stage.request

        def is_response(record):
            return record.stage == Stage.response

        def is_stream(record):
            return getattr(record, "stream_part", False)

        def match_all(*fns):
            def check(val):
                return all(fn(val) for fn in fns)

            return check

        def extract_trace(record):
            return record.nameko_trace

        def extract_records():
            trace_records = list(filter(is_trace, caplog.records))

            request_trace = extract_trace(next(filter(is_request, trace_records)))
            response_trace = extract_trace(next(filter(is_response, trace_records)))

            request_stream = list(
                map(
                    extract_trace,
                    filter(match_all(is_request, is_stream), trace_records),
                )
            )
            response_stream = list(
                map(
                    extract_trace,
                    filter(match_all(is_response, is_stream), trace_records),
                )
            )
            return request_trace, response_trace, request_stream, response_stream

        return extract_records

    @pytest.fixture
    def check_trace(self):
        def check(data, requires):
            for key, value in requires.items():
                if callable(value):
                    assert value(data[key])
                else:
                    assert data[key] == value

        return check

    def test_unary_unary(self, client, protobufs, get_log_records, check_trace):
        response = client.unary_unary(protobufs.ExampleRequest(value="A"))
        assert response.message == "A"

        request_trace, response_trace, request_stream, result_stream = get_log_records()

        common = {
            "call_id": "example.unary_unary.0",
            "call_id_stack": ["example.unary_unary.0"],
            "entrypoint_name": "unary_unary",
            "entrypoint_type": "Grpc",
            "service": "example",
        }

        check_trace(
            request_trace,
            dict(
                common, **{"stage": "request", "cardinality": Cardinality.UNARY_UNARY}
            ),
        )

        check_trace(
            response_trace,
            dict(
                common,
                **{
                    "stage": "response",
                    "cardinality": Cardinality.UNARY_UNARY,
                    "response": response,
                    "response_status": "success",
                    "response_time": lambda value: value > 0,
                }
            ),
        )

        assert len(request_stream) == 0

        assert len(result_stream) == 0

    def test_unary_stream(self, client, protobufs, get_log_records, check_trace):
        responses = client.unary_stream(
            protobufs.ExampleRequest(value="A", response_count=2)
        )
        assert [(response.message, response.seqno) for response in responses] == [
            ("A", 1),
            ("A", 2),
        ]

        request_trace, response_trace, request_stream, result_stream = get_log_records()

        common = {
            "call_id": "example.unary_stream.0",
            "call_id_stack": ["example.unary_stream.0"],
            "entrypoint_name": "unary_stream",
            "entrypoint_type": "Grpc",
            "service": "example",
        }

        check_trace(
            request_trace,
            dict(
                common, **{"stage": "request", "cardinality": Cardinality.UNARY_STREAM}
            ),
        )

        check_trace(
            response_trace,
            dict(
                common,
                **{
                    "stage": "response",
                    "cardinality": Cardinality.UNARY_STREAM,
                    "response": "streaming",
                    "response_status": "success",
                    "response_time": lambda value: value > 0,
                }
            ),
        )

        assert len(request_stream) == 0

        assert len(result_stream) == 2
        for index, trace in enumerate(result_stream, 1):
            check_trace(
                trace,
                dict(
                    common,
                    **{
                        "stage": "response",
                        "cardinality": Cardinality.UNARY_STREAM,
                        "stream_part": index,
                        "response_time": None,
                        "stream_age": lambda value: value > 0,
                    }
                ),
            )

    def test_stream_unary(self, client, protobufs, get_log_records, check_trace):
        def generate_requests():
            for value in ["A", "B"]:
                yield protobufs.ExampleRequest(value=value)

        response = client.stream_unary(generate_requests())
        assert response.message == "A,B"

        request_trace, response_trace, request_stream, result_stream = get_log_records()

        common = {
            "call_id": "example.stream_unary.0",
            "call_id_stack": ["example.stream_unary.0"],
            "entrypoint_name": "stream_unary",
            "entrypoint_type": "Grpc",
            "service": "example",
        }

        check_trace(
            request_trace,
            dict(
                common, **{"stage": "request", "cardinality": Cardinality.STREAM_UNARY}
            ),
        )

        check_trace(
            response_trace,
            dict(
                common,
                **{
                    "stage": "response",
                    "cardinality": Cardinality.STREAM_UNARY,
                    "response": response,
                    "response_status": "success",
                    "response_time": lambda value: value > 0,
                }
            ),
        )

        assert len(request_stream) == 2
        for index, trace in enumerate(request_stream, 1):
            check_trace(
                trace,
                dict(
                    common,
                    **{
                        "stage": "request",
                        "cardinality": Cardinality.STREAM_UNARY,
                        "stream_part": index,
                        "stream_age": lambda value: value > 0,
                    }
                ),
            )

        assert len(result_stream) == 0

    def test_stream_stream(self, client, protobufs, get_log_records, check_trace):
        def generate_requests():
            for value in ["A", "B"]:
                yield protobufs.ExampleRequest(value=value)

        responses = client.stream_stream(generate_requests())
        assert [(response.message, response.seqno) for response in responses] == [
            ("A", 1),
            ("B", 2),
        ]

        request_trace, response_trace, request_stream, result_stream = get_log_records()

        common = {
            "call_id": "example.stream_stream.0",
            "call_id_stack": ["example.stream_stream.0"],
            "entrypoint_name": "stream_stream",
            "entrypoint_type": "Grpc",
            "service": "example",
        }

        check_trace(
            request_trace,
            dict(
                common, **{"stage": "request", "cardinality": Cardinality.STREAM_STREAM}
            ),
        )

        check_trace(
            response_trace,
            dict(
                common,
                **{
                    "stage": "response",
                    "cardinality": Cardinality.STREAM_STREAM,
                    "response": "streaming",
                    "response_status": "success",
                    "response_time": lambda value: value > 0,
                }
            ),
        )

        assert len(request_stream) == 2
        for index, trace in enumerate(request_stream, 1):
            check_trace(
                trace,
                dict(
                    common,
                    **{
                        "stage": "request",
                        "cardinality": Cardinality.STREAM_STREAM,
                        "stream_part": index,
                        "stream_age": lambda value: value > 0,
                    }
                ),
            )

        assert len(result_stream) == 2
        for index, trace in enumerate(result_stream, 1):
            check_trace(
                trace,
                dict(
                    common,
                    **{
                        "stage": "response",
                        "cardinality": Cardinality.STREAM_STREAM,
                        "stream_part": index,
                        "response_time": None,
                        "stream_age": lambda value: value > 0,
                    }
                ),
            )

    def test_error_before_response(
        self, client, protobufs, get_log_records, check_trace
    ):
        with pytest.raises(GrpcError) as error:
            client.unary_error(protobufs.ExampleRequest(value="A"))
        assert error.value.status == StatusCode.UNKNOWN
        assert error.value.details == "Exception calling application: boom"

        request_trace, response_trace, request_stream, result_stream = get_log_records()

        common = {
            # XXX add call_args here (for all tests)
            "call_id": "example.unary_error.0",
            "call_id_stack": ["example.unary_error.0"],
            "entrypoint_name": "unary_error",
            "entrypoint_type": "Grpc",
            "service": "example",
        }

        check_trace(
            request_trace,
            dict(
                common, **{"stage": "request", "cardinality": Cardinality.UNARY_UNARY}
            ),
        )

        check_trace(
            response_trace,
            dict(
                common,
                **{
                    "stage": "response",
                    "cardinality": Cardinality.UNARY_UNARY,
                    "response_status": "error",
                    "response_time": lambda value: value > 0,
                    "exception_value": "boom",
                    "exception_type": "Error",
                    "exception_path": "example_nameko.Error",
                    "exception_args": ["boom"],
                    "exception_traceback": lambda tb: 'raise Error("boom")' in tb,
                    "exception_expected": True,
                }
            ),
        )

        assert len(request_stream) == 0

        assert len(result_stream) == 0

    def test_error_while_streaming_response(
        self, client, protobufs, get_log_records, check_trace
    ):
        res = client.stream_error(
            protobufs.ExampleRequest(value="A", response_count=10)
        )
        with pytest.raises(GrpcError) as error:
            list(res)

        assert error.value.status == StatusCode.UNKNOWN
        assert error.value.details == "Exception iterating responses: boom"

        request_trace, response_trace, request_stream, result_stream = get_log_records()

        common = {
            # XXX add call_args here (for all tests)
            "call_id": "example.stream_error.0",
            "call_id_stack": ["example.stream_error.0"],
            "entrypoint_name": "stream_error",
            "entrypoint_type": "Grpc",
            "service": "example",
        }

        check_trace(
            request_trace,
            dict(
                common, **{"stage": "request", "cardinality": Cardinality.UNARY_STREAM}
            ),
        )

        check_trace(
            response_trace,
            dict(
                common,
                **{
                    "stage": "response",
                    "cardinality": Cardinality.UNARY_STREAM,
                    "response_status": "success",  # XXX URM
                    "response_time": lambda value: value > 0,
                }
            ),
        )

        assert len(request_stream) == 0

        assert len(result_stream) == 10

        # check first 9 stream parts
        for index, trace in enumerate(result_stream[:-1], 1):
            check_trace(
                trace,
                dict(
                    common,
                    **{
                        "stage": "response",
                        "cardinality": Cardinality.UNARY_STREAM,
                        "stream_part": index,
                        # "result": "something",
                        "response_status": "success",
                        "response_time": None,
                        "stream_age": lambda value: value > 0,
                    }
                ),
            )

        # check last stream part
        check_trace(
            result_stream[-1],
            dict(
                common,
                **{
                    "stage": "response",
                    "cardinality": Cardinality.UNARY_STREAM,
                    "stream_part": 10,
                    "response_status": "error",
                    "response_time": None,
                    "stream_age": lambda value: value > 0,
                    "exception_value": "boom",
                    "exception_type": "Error",
                    "exception_path": "example_nameko.Error",
                    "exception_args": ["boom"],
                    "exception_traceback": lambda tb: 'raise Error("boom")' in tb,
                    "exception_expected": True,
                }
            ),
        )
