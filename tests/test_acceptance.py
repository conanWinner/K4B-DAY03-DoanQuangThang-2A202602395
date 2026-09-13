import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('acceptance', Path(__file__).resolve().parents[1] / 'scripts/run_acceptance.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class AcceptanceChecksTests(unittest.TestCase):
    def test_final_answer_does_not_hide_forecast_failure(self):
        trace = [{'action_type': 'TOOL_EXECUTION', 'tool_name': 'get_weather_forecast',
                  'arguments': {'latitude': 12.6667, 'longitude': 108.05, 'days': 3},
                  'observation': {'status': 'WEATHER_ERROR'}}, {'action_type': 'FINAL_ANSWER'}]
        checks = module.check_case('TC02', trace, Path('unused'))
        self.assertFalse(checks['live_forecast'])
        self.assertTrue(checks['final_answer'])

    def test_tc04_requires_order_and_matching_coordinates(self):
        plot = {'action_type': 'TOOL_EXECUTION', 'tool_name': 'get_plot_info',
                'arguments': {'plot_id': 'CF001'}, 'observation': {'status': 'SUCCESS',
                'data': {'latitude': 12.6667, 'longitude': 108.05}}}
        weather = {'action_type': 'TOOL_EXECUTION', 'tool_name': 'get_weather_forecast',
                   'arguments': {'latitude': 12.6667, 'longitude': 108.05, 'days': 3},
                   'observation': {'status': 'SUCCESS'}}
        self.assertFalse(module.check_case('TC04', [weather, plot], Path('unused'))['plot_then_weather'])
        self.assertTrue(module.check_case('TC04', [plot, weather], Path('unused'))['plot_then_weather'])
        weather['arguments']['latitude'] = 0
        self.assertFalse(module.check_case('TC04', [plot, weather], Path('unused'))['plot_then_weather'])
