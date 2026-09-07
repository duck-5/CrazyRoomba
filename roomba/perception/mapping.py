"""
Occupancy Grid Mapping for Roomba.
Maintains a 2D grid of the environment.
"""

import math
from typing import Dict, Any, List

class OccupancyGrid:
    def __init__(self, cell_size_mm: int = 50, width_cells: int = 200, height_cells: int = 200):
        self.cell_size_mm = cell_size_mm
        self.width = width_cells
        self.height = height_cells
        
        # Grid origin (robot starts at center of the grid)
        self.origin_x = width_cells // 2
        self.origin_y = height_cells // 2
        
        # 0 = Unknown, 1 = Free, 2 = Wall/Obstacle, 3 = Cliff/Void
        self.grid = [[0 for _ in range(self.width)] for _ in range(self.height)]
        
        # Track robot pose (x, y, theta in mm and radians)
        self.robot_x = 0.0
        self.robot_y = 0.0
        self.robot_theta = 0.0

    def mm_to_cell(self, x_mm: float, y_mm: float) -> tuple[int, int]:
        """Convert physical coordinates to grid indices."""
        cx = self.origin_x + int(x_mm / self.cell_size_mm)
        cy = self.origin_y + int(y_mm / self.cell_size_mm)
        return cx, cy

    def update_pose(self, x_mm: float, y_mm: float, theta_rad: float):
        """Update robot position and mark current cell as free."""
        self.robot_x = x_mm
        self.robot_y = y_mm
        self.robot_theta = theta_rad
        
        cx, cy = self.mm_to_cell(self.robot_x, self.robot_y)
        self._set_cell(cx, cy, 1)  # 1 = Free

    def mark_obstacle(self, distance_mm: float, angle_offset_rad: float = 0.0):
        """Mark an obstacle relative to the robot's current pose."""
        angle = self.robot_theta + angle_offset_rad
        ox = self.robot_x + math.cos(angle) * distance_mm
        oy = self.robot_y + math.sin(angle) * distance_mm
        cx, cy = self.mm_to_cell(ox, oy)
        self._set_cell(cx, cy, 2)  # 2 = Wall

    def mark_cliff(self, distance_mm: float, angle_offset_rad: float = 0.0):
        """Mark a cliff/void relative to the robot's current pose."""
        angle = self.robot_theta + angle_offset_rad
        ox = self.robot_x + math.cos(angle) * distance_mm
        oy = self.robot_y + math.sin(angle) * distance_mm
        cx, cy = self.mm_to_cell(ox, oy)
        self._set_cell(cx, cy, 3)  # 3 = Cliff

    def _set_cell(self, cx: int, cy: int, state: int):
        if 0 <= cx < self.width and 0 <= cy < self.height:
            self.grid[cy][cx] = state

    def get_map_data(self) -> Dict[str, Any]:
        """Return the grid data for UI rendering."""
        return {
            "cell_size_mm": self.cell_size_mm,
            "width": self.width,
            "height": self.height,
            "origin_x": self.origin_x,
            "origin_y": self.origin_y,
            "robot": {
                "cx": self.origin_x + int(self.robot_x / self.cell_size_mm),
                "cy": self.origin_y + int(self.robot_y / self.cell_size_mm),
                "theta": self.robot_theta
            },
            # Return sparse representation for efficiency
            "cells": [
                {"x": x, "y": y, "v": self.grid[y][x]}
                for y in range(self.height)
                for x in range(self.width)
                if self.grid[y][x] != 0
            ]
        }
