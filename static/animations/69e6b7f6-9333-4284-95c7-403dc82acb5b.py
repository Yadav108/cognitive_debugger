from manim import *

class CognitiveDebuggerScene(Scene):
    def construct(self):
        # Act 1: Physics diagram
        ladder = Line(ORIGIN, 4 * RIGHT).rotate(60 * DEGREES)
        wall = Line(4 * RIGHT, 4 * RIGHT + 2 * UP)
        floor = Line(ORIGIN, 4 * RIGHT)
        person = Dot(3 * RIGHT).rotate(60 * DEGREES)
        self.add(ladder, wall, floor, person)
        self.play(Create(ladder), Create(wall), Create(floor), Create(person))
        self.wait(0.5)
        label1 = Text("Ladder", font_size=24).next_to(ladder, DOWN)
        label2 = Text("Wall", font_size=24).next_to(wall, RIGHT)
        label3 = Text("Floor", font_size=24).next_to(floor, DOWN)
        label4 = Text("Person", font_size=24).next_to(person, RIGHT)
        self.play(Write(label1), Write(label2), Write(label3), Write(label4))
        self.wait(0.5)
        self.play(FadeOut(*self.mobjects))
        self.wait(0.3)

        # Act 2: Solution steps
        equation1 = MathTex(r"\sum M_B = 0")
        equation2 = MathTex(r"F_{wall} \cdot 4 \sin(60^\circ) - m_{person} \cdot g \cdot 3 \cos(60^\circ) - m_{ladder} \cdot g \cdot 2 \cos(60^\circ) = 0")
        equation3 = MathTex(r"F_{friction} = m_{person} \cdot g + m_{ladder} \cdot g")
        self.play(Write(equation1))
        self.wait(0.5)
        self.play(Write(equation2))
        self.wait(0.5)
        self.play(Write(equation3))
        self.wait(0.5)
        self.play(FadeOut(*self.mobjects))
        self.wait(0.3)

        # Act 3: Misconception highlight
        incorrect_equation = MathTex(r"\sum M_B = F_{wall} \cdot 4 \sin(60^\circ) - m_{person} \cdot g \cdot 3 \cos(60^\circ)")
        self.play(Write(incorrect_equation))
        rect = SurroundingRectangle(incorrect_equation, buff=0.2)
        error_label = Text("Incorrect System Definition", font_size=24, color=RED).next_to(rect, UP)
        self.play(Create(rect), Write(error_label))
        self.wait(0.5)