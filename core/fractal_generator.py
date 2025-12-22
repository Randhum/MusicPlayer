"""Fractal generator using perfect-shuffle algorithm.

Based on the perfect-shuffle algorithm from:
https://github.com/xcontcom/perfect-shuffle

The algorithm generates deterministic fractals using recursive spatial
permutations of binary fields.
"""

from typing import List, Optional


class FractalGenerator:
    """Generates fractals using the perfect-shuffle algorithm."""
    
    def __init__(self, rules: List[int] = [2, 1, 15, 14], iterations: int = 8):
        """
        Initialize the fractal generator.
        
        Args:
            rules: List of 4 rule values (0-15) that define the shuffle pattern
            iterations: Number of iterations (determines size: 2^(iterations+1))
        """
        if len(rules) != 4:
            raise ValueError("Rules must be a list of 4 integers (0-15)")
        if not all(0 <= r <= 15 for r in rules):
            raise ValueError("All rules must be between 0 and 15")
        
        self.rules = rules
        self.iterations = iterations
        self._cache: Optional[List[List[int]]] = None
    
    def generate(self) -> List[List[int]]:
        """
        Generate the fractal pattern.
        
        Returns:
            2D list of binary values (0 or 1)
        """
        if self._cache is not None:
            return self._cache
        
        # Start with 2x2 grid
        size = 2 ** (self.iterations + 1)
        grid = [[0 for _ in range(size)] for _ in range(size)]
        
        # Initialize 2x2 base
        grid[0][0] = 0
        grid[0][1] = 0
        grid[1][0] = 0
        grid[1][1] = 1
        
        # Apply iterations
        current_size = 2
        for iteration in range(self.iterations):
            new_size = current_size * 2
            new_grid = [[0 for _ in range(new_size)] for _ in range(new_size)]
            
            # Process each 2x2 block in the current grid
            for y in range(0, current_size, 2):
                for x in range(0, current_size, 2):
                    # Get the 2x2 block values
                    block = [
                        grid[y][x], grid[y][x+1],
                        grid[y+1][x], grid[y+1][x+1]
                    ]
                    
                    # Apply each rule to generate 4 new 2x2 blocks
                    for rule_idx, rule in enumerate(self.rules):
                        # Calculate position of new block
                        new_y = y * 2 + (rule_idx // 2) * 2
                        new_x = x * 2 + (rule_idx % 2) * 2
                        
                        # Apply shuffle rule
                        shuffled = self._apply_shuffle_rule(block, rule)
                        
                        # Place shuffled values in new grid
                        new_grid[new_y][new_x] = shuffled[0]
                        new_grid[new_y][new_x+1] = shuffled[1]
                        new_grid[new_y+1][new_x] = shuffled[2]
                        new_grid[new_y+1][new_x+1] = shuffled[3]
            
            grid = new_grid
            current_size = new_size
        
        self._cache = grid
        return grid
    
    def _apply_shuffle_rule(self, block: List[int], rule: int) -> List[int]:
        """
        Apply a shuffle rule to a 2x2 block.
        
        The rule (0-15) determines how the 4 values are rearranged.
        Each rule is a perfect shuffle - a deterministic permutation.
        
        Args:
            block: List of 4 values from the 2x2 block [top-left, top-right, bottom-left, bottom-right]
            rule: Rule number (0-15)
        
        Returns:
            Shuffled list of 4 values
        """
        # Rule patterns: all 16 possible 2x2 binary patterns
        rule_patterns = [
            [0, 0, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0], [0, 0, 1, 1],
            [0, 1, 0, 0], [0, 1, 0, 1], [0, 1, 1, 0], [0, 1, 1, 1],
            [1, 0, 0, 0], [1, 0, 0, 1], [1, 0, 1, 0], [1, 0, 1, 1],
            [1, 1, 0, 0], [1, 1, 0, 1], [1, 1, 1, 0], [1, 1, 1, 1],
        ]
        
        # Use rule to determine output based on input
        input_sum = sum(block)
        pattern = rule_patterns[rule]
        
        if input_sum == 0:
            # All zeros: use rule pattern directly
            output = pattern[:]
        elif input_sum == 4:
            # All ones: invert rule pattern
            output = [1 - p for p in pattern]
        else:
            # Mixed: combine rule pattern with input structure
            output = pattern[:]
            # Preserve input structure where it dominates
            if input_sum >= 2:
                # Majority ones: take max of pattern and input
                output = [max(output[i], block[i]) for i in range(4)]
            else:
                # Majority zeros: take min of pattern and input
                output = [min(output[i], block[i]) for i in range(4)]
        
        return output
    
    def get_pixel(self, x: int, y: int, width: int, height: int) -> int:
        """
        Get the pixel value at a specific position.
        
        Args:
            x: X coordinate (0 to width-1)
            y: Y coordinate (0 to height-1)
            width: Output width
            height: Output height
        
        Returns:
            Binary value (0 or 1)
        """
        fractal = self.generate()
        fractal_size = len(fractal)
        
        # Scale coordinates to fractal size
        fx = int(x * fractal_size / width) if width > 0 else 0
        fy = int(y * fractal_size / height) if height > 0 else 0
        
        # Clamp to valid range
        fx = max(0, min(fx, fractal_size - 1))
        fy = max(0, min(fy, fractal_size - 1))
        
        return fractal[fy][fx]
    
    def clear_cache(self):
        """Clear the cached fractal to force regeneration."""
        self._cache = None

