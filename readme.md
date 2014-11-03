Boardfit
========

Boardfit is a 2D "cutting stock" optimizing program.

This program finds the best layout for a collection of arbitrary shaped parts within a stock material of a given width.  The original application was to determine the best layout for a set of irregular pieces within hardwood board such that a minimum length of the wood would be used.

For inputs, the program takes:

- A set of parts that will be fit within the stock.  The parts are specified as greyscale binary PPM (P5) files.  All files must be the same scale.

- The breadth of the stock (in the program this is called `height`).  The height is given in the pixel units of the part files.

- A `gap` to reserve between parts.  The parts can be placed right up to the edge of the stock, but this much space is left between them.  The gaps is at the same scale as the parts.

The program outputs:

- A ppm file of the best fit of the parts minimizing consumed stock.

- The width of the stock necessary to fit all of the parts.

The parts are placed within constrained orientation, only allowing vertical or horizontal flips (not arbitrary rotations), as the original intent is to place wooden pieces where the grain direction is critical.


